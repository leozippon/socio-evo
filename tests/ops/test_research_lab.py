"""Single-lab launch retains real preflight, frozen settings and resume checks."""

import json

import pytest

from infrastructure.storage.run_directory import RunStatus
from ops.research import model_service, run_lab, run_pair


def test_model_command_preserves_pilot_defaults_and_allows_single_gpu():
    old = model_service.command("python", 8040, 8)
    single = model_service.command(
        "python", 8041, 4, tensor_parallel_size=1, max_model_len=131072, kv_cache_dtype="auto"
    )
    assert old[old.index("--tensor-parallel-size") + 1] == "2"
    assert old[old.index("--kv-cache-dtype") + 1] == "fp8_e4m3"
    assert single[single.index("--tensor-parallel-size") + 1] == "1"
    assert single[single.index("--max-model-len") + 1] == "131072"
    assert "--api-key" not in single
    assert "--enable-auto-tool-choice" in single and "--reasoning-parser" in single


def test_model_waits_for_resumed_run_before_stopping_on_old_terminal_manifest(tmp_path):
    manifest = tmp_path / "runs/lab/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"status": "interrupted"}))
    assert model_service.experiment_state(tmp_path, False) == (False, False)
    manifest.write_text(json.dumps({"status": "running"}))
    assert model_service.experiment_state(tmp_path, False) == (True, False)
    for status in ("interrupted", "failed", "completed"):
        manifest.write_text(json.dumps({"status": status}))
        assert model_service.experiment_state(tmp_path, True) == (True, True)


@pytest.mark.parametrize("preflight_mode", ["failure", "only", "launch"])
def test_single_lab_never_runs_before_preflight(tmp_path, monkeypatch, preflight_mode):
    monkeypatch.setattr(run_pair, "PROJECT_STORAGE", tmp_path)
    monkeypatch.setenv("LIGHTING_API_KEY", "test-model-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-search-key")
    events = []

    async def preflight(configs, control):
        events.append("preflight")
        assert list(configs) == ["lab"]
        assert configs["lab"].town.research.gpus == "device=1"
        if preflight_mode == "failure":
            raise RuntimeError("Real provider preflight failed")
        return {"ok": True}

    async def run(config, root, *, resume, until_day):
        assert preflight_mode == "launch"
        assert events == ["preflight"]
        assert config.town.seed == 19 and until_day == 8 and not resume
        assert (root / "lab-seed-19/lab.yaml").is_file()
        events.append("run")
        return root / config.name, RunStatus.INTERRUPTED

    monkeypatch.setattr(run_lab, "preflight", preflight)
    monkeypatch.setattr(run_lab, "run", run)
    args = [
        "--runs-root",
        str(tmp_path / "runs"),
        "--config",
        str(run_pair.PROJECT_ROOT / "experiments/configs/autoresearch-academy.yaml"),
        "--seed",
        "19",
        "--until-day",
        "8",
    ]
    if preflight_mode == "only":
        args.append("--preflight-only")
    if preflight_mode == "failure":
        with pytest.raises(RuntimeError, match="preflight failed"):
            run_lab.main(args)
    else:
        assert run_lab.main(args) == 0
    assert events == (["preflight", "run"] if preflight_mode == "launch" else ["preflight"])
    assert not any((tmp_path / "runs").glob("*/manifest.json"))


def test_missing_lab_credentials_leaves_no_state(tmp_path, monkeypatch):
    monkeypatch.setattr(run_pair, "PROJECT_STORAGE", tmp_path)
    monkeypatch.delenv("LIGHTING_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    root = tmp_path / "runs"
    with pytest.raises(ValueError, match="Missing credential"):
        run_lab.main(
            [
                "--runs-root",
                str(root),
                "--config",
                str(run_pair.PROJECT_ROOT / "experiments/configs/autoresearch-academy.yaml"),
            ]
        )
    assert not root.exists()
