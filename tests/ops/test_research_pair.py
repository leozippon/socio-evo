"""The real-run helper refuses local storage and incomplete setup before starting either arm."""

import json
import os

import pytest

from infrastructure.llm import LLMResponse, ToolCall
from infrastructure.storage.run_directory import RunDirectory, RunStatus
from ops.research import run_pair as pair


def configs(seed=23):
    return {
        arm: pair.configuration(
            pair.PROJECT_ROOT / f"experiments/configs/autoresearch-{arm}.yaml", seed, None
        )
        for arm in pair.ARMS
    }


def test_requires_remote_storage_and_credentials_before_creating_runs(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="absolute path"):
        pair.remote_root(tmp_path / "runs")
    monkeypatch.setattr(pair, "PROJECT_STORAGE", tmp_path)
    monkeypatch.delenv("LIGHTING_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    destination = tmp_path / "runs"
    with pytest.raises(ValueError, match="LIGHTING_API_KEY.*TAVILY_API_KEY"):
        pair.main(["--runs-root", str(destination)])
    assert not destination.exists()
    assert {c.town.seed for c in configs().values()} == {23}
    assert all(c.name.endswith("-seed-23") for c in configs().values())


def test_resume_uses_frozen_configs_skips_finished_arm_and_refuses_live_process(tmp_path):
    configured = configs()
    for arm, config in configured.items():
        directory = RunDirectory.create(tmp_path, config.name, config=config, code_revision="test")
        directory.checkpoint_path(7 if arm == "town" else 1).write_text("{}")
        directory.update_manifest(status=RunStatus.INTERRUPTED, pid=None)
    active = pair.pending(configured, tmp_path, resume=True, until_day=7)
    assert list(active) == ["academy"]
    with pytest.raises(FileExistsError):
        pair.pending(configured, tmp_path, resume=False, until_day=7)
    changed = configs()
    changed["academy"] = changed["academy"].model_copy(update={"days": 35})
    with pytest.raises(ValueError, match="Configuration differs"):
        pair.pending(changed, tmp_path, resume=True, until_day=7)
    directory = RunDirectory.open(tmp_path / configured["academy"].name)
    directory.update_manifest(status=RunStatus.RUNNING, pid=os.getpid())
    with pytest.raises(ValueError, match="live process"):
        pair.pending(configured, tmp_path, resume=True, until_day=7)


def test_failed_preflight_never_launches_either_arm(tmp_path, monkeypatch):
    monkeypatch.setattr(pair, "PROJECT_STORAGE", tmp_path)
    monkeypatch.setenv("LIGHTING_API_KEY", "private-test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "private-search-key")

    async def fail(*args):
        raise RuntimeError("Preflight failed at judge:town")

    async def forbidden(*args, **kwargs):
        pytest.fail("No arm may start after a failed preflight")

    monkeypatch.setattr(pair, "preflight", fail)
    monkeypatch.setattr(pair, "launch", forbidden)
    with pytest.raises(RuntimeError, match="Preflight failed"):
        pair.main(["--runs-root", str(tmp_path / "runs")])
    assert not any((tmp_path / "runs").glob("autoresearch-*"))


@pytest.mark.asyncio
async def test_frozen_profile_conflict_prevents_both_launches(tmp_path, monkeypatch):
    control = tmp_path / "control"
    control.mkdir()
    (control / "academy.yaml").write_text("different frozen profile")

    async def forbidden(*args, **kwargs):
        pytest.fail("Neither process may start before both profiles are checked")

    monkeypatch.setattr(pair.asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(ValueError, match="Frozen launch configuration differs"):
        await pair.launch(configs(), tmp_path, control, resume=True, until_day=7)


@pytest.mark.asyncio
async def test_pair_records_independent_exit_status_and_propagates_options(tmp_path, monkeypatch):
    configured = configs()
    control = tmp_path / "control"
    control.mkdir()
    calls = []

    class Process:
        pid = 1234

        def __init__(self, arm):
            self.returncode = 0 if arm == "town" else 1

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        calls.append(args)
        arm = args[args.index("--arm") + 1]
        run = tmp_path / configured[arm].name
        run.mkdir()
        (run / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "interrupted" if arm == "town" else "failed",
                }
            )
        )
        return Process(arm)

    monkeypatch.setattr(pair.asyncio, "create_subprocess_exec", spawn)
    assert await pair.launch(configured, tmp_path, control, resume=True, until_day=7) == 1
    assert len(calls) == 2
    assert all("--resume" in call and call[-2:] == ("--until-day", "7") for call in calls)
    status = json.loads((control / "status.json").read_text())
    assert status["town"]["exit_code"] == 0
    assert status["academy"]["exit_code"] == 1
    assert all(arm["pid"] is None for arm in status.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("scholar_enabled", [False, True])
@pytest.mark.parametrize("persistent_runtime", [False, True])
@pytest.mark.parametrize("review_style", ["standard", "conference"])
async def test_preflight_checks_real_contracts_and_cleans_temporary_workspace(
    tmp_path, monkeypatch, scholar_enabled, persistent_runtime, review_style
):
    monkeypatch.setenv("LIGHTING_API_KEY", "private-test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "private-search-key")
    seen = []

    class Client:
        async def stream(self, request):
            seen.append("actor")
            if request.tools:
                return LLMResponse(
                    text="",
                    latency=0,
                    reasoning="Call echo.",
                    tool_calls=(ToolCall(id="echo-1", name="echo", arguments={"text": "hello"}),),
                )
            assert any(m.tool_call_id == "echo-1" for m in request.messages)
            assert next(m for m in request.messages if m.role == "assistant").reasoning_content
            return LLMResponse(text="hello", latency=0)

        async def complete(self, request):
            seen.append("judge")
            assert request.json_schema
            return LLMResponse(text='{"ok":true}', latency=0)

    def source(query):
        seen.append("source")
        return {"source": "https://example.org", "results": []}

    def scholar(query):
        assert scholar_enabled, "Disabled Semantic Scholar must not be probed"
        return source(query)

    async def command(image, files, records, cmd, timeout, **kwargs):
        seen.append("docker")
        assert kwargs["cpus"] == 8 and kwargs["memory"] == "32g"
        (files / "probe.txt").write_text("ok")
        if persistent_runtime:
            assert kwargs["runtime_dir"].parent == files.parent
            assert "loss.backward()" in cmd or "torch.load(" in cmd
            (files / "gpu-uuids.txt").write_text("GPU-research\n")
        if review_style == "conference" and "latexmk" in cmd:
            assert "-halt-on-error" in cmd and "probe-figure.pdf" in cmd
            assert "\\bibliography{probe}" in (files / "probe.tex").read_text()
            (files / "probe.pdf").write_bytes(b"%PDF-1.4\n")
            (files / "probe.bbl").write_text("Probe citation")
            (files / "probe.log").write_text("Output written on probe.pdf")
        return {"exit_code": 0, "timed_out": False}

    monkeypatch.setattr(pair, "create_client", lambda config: Client())
    monkeypatch.setattr(pair.research_sources, "search_web", source)
    monkeypatch.setattr(pair.research_sources, "search", scholar)
    monkeypatch.setattr(pair.research_sources, "curl_source", source)
    monkeypatch.setattr(pair.research_workspace, "require_image", lambda image: None)
    monkeypatch.setattr(pair.research_workspace, "execute", command)
    monkeypatch.setattr(pair.subprocess, "check_output", lambda *a, **k: "GPU-research\n")
    configured = configs()
    for arm, config in configured.items():
        configured[arm] = config.model_copy(
            update={"town": config.town.model_copy(update={
                "research": config.town.research.model_copy(update={"review_style": review_style})
            })}
        )
    if persistent_runtime:
        for arm, config in configured.items():
            town = config.town
            configured[arm] = config.model_copy(
                update={
                    "town": town.model_copy(
                        update={
                            "research": town.research.model_copy(
                                update={"persistent_runtime": True, "gpus": "device=1"}
                            )
                        }
                    )
                }
            )
    if scholar_enabled:
        town = configured["town"].town
        configured["town"] = configured["town"].model_copy(
            update={
                "town": town.model_copy(
                    update={"research": town.research.model_copy(update={"semantic_scholar": True})}
                )
            }
        )
    report = await pair.preflight(configured, tmp_path)
    assert report["ok"]
    assert seen == ["actor", "actor", "judge"] + ["source"] * (3 if scholar_enabled else 2) + [
        "docker"
    ] * (2 if persistent_runtime else 1)
    if persistent_runtime:
        assert report["checks"]["docker:town"]["gpu_uuids"] == ["GPU-research"]
        assert report["checks"]["docker:town"]["checkpoint_reload"]
    if review_style == "conference":
        assert report["checks"]["docker:town"]["latex_compiled"]
    if not scholar_enabled:
        assert report["checks"]["semantic_scholar"] == {"enabled": False, "status": "disabled"}
    assert not list(tmp_path.glob("preflight-*"))
    assert "private-" not in (tmp_path / "preflight.json").read_text()

    if review_style == "conference":
        async def missing_bibliography(*args, **kwargs):
            result = await command(*args, **kwargs)
            if "latexmk" in args[3]:
                (args[1] / "probe.bbl").write_text("")
            return result

        monkeypatch.setattr(pair.research_workspace, "execute", missing_bibliography)
        with pytest.raises(RuntimeError, match="Preflight failed at docker:town"):
            await pair.preflight(configured, tmp_path)
        monkeypatch.setattr(pair.research_workspace, "execute", command)

    def failed(query):
        raise ValueError("HTTP 429")

    failing = "search" if scholar_enabled else "search_web"
    stage = "semantic_scholar" if scholar_enabled else "tavily"
    monkeypatch.setattr(pair.research_sources, failing, failed)
    with pytest.raises(RuntimeError, match=f"Preflight failed at {stage}"):
        await pair.preflight(configured, tmp_path)
    assert not json.loads((tmp_path / "preflight.json").read_text())["ok"]

    if persistent_runtime:
        monkeypatch.setattr(pair.research_sources, failing, scholar if scholar_enabled else source)
        monkeypatch.setattr(pair.subprocess, "check_output", lambda *a, **k: "GPU-model\n")
        with pytest.raises(RuntimeError, match="Preflight failed at docker:town"):
            await pair.preflight(configured, tmp_path)
