import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tasks.swebench import preflight
from tasks.swebench.pilot import execute
from tasks.swebench.provider import SWEbenchTaskProvider


@pytest.fixture
def docker_stub(monkeypatch):
    removed = []
    container = SimpleNamespace(
        image=SimpleNamespace(id="sha256:test"), remove=lambda **kw: removed.append(kw)
    )
    client = SimpleNamespace(
        containers=SimpleNamespace(get=lambda name: container), close=lambda: None
    )
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: client))
    monkeypatch.setattr(preflight, "command", lambda *a, **kw: "id")
    monkeypatch.setattr(preflight, "captured_exec", lambda *a: SimpleNamespace(output=b"base\n"))
    return removed


def test_preflight_checks_exact_django_launcher_and_records_result(
    tmp_path, monkeypatch, docker_stub
):
    seen = []

    def run(name, script, seconds):
        seen.append(script)
        return {"exit_code": 0, "output": "Python 3.11\n4.2"}

    monkeypatch.setattr(preflight, "execute", run)
    report = preflight.inspect_environment("django__django-1", "django/django", "base", tmp_path)
    assert report["status"] == "passed"
    assert "python tests/runtests.py --help" in seen[0]
    assert "DJANGO_SETTINGS_MODULE=test_sqlite" in seen[0]
    assert "django.setup()" in seen[0]
    assert "<test-label>" in report["guide"]
    assert docker_stub == [{"force": True}]
    assert json.loads((tmp_path / "django__django-1.json").read_text())["image_id"] == "sha256:test"


def test_failed_probe_is_environment_error_and_container_is_removed(
    tmp_path, monkeypatch, docker_stub
):
    monkeypatch.setattr(preflight, "execute", lambda *a: {"exit_code": 1, "output": "No pytest"})
    with pytest.raises(preflight.EnvironmentPreflightError):
        preflight.inspect_environment("org__repo-1", "org/repo", "base", tmp_path)
    assert json.loads((tmp_path / "org__repo-1.json").read_text())["status"] == "failed"
    assert docker_stub == [{"force": True}]


def test_guidance_uses_only_public_environment_information_and_caches(tmp_path, monkeypatch):
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                dict(
                    instance_id="org__repo-1",
                    repo="org/repo",
                    base_commit="base",
                    problem_statement="Repair it",
                    patch="SECRET",
                    test_patch="SECRET",
                    FAIL_TO_PASS="SECRET",
                )
            ]
        )
    )
    calls = []

    def check(*args):
        calls.append(args)
        return {"guide": "Use python -m pytest <test-path>", "image_id": "test"}

    monkeypatch.setattr(preflight, "inspect_environment", check)
    p = SWEbenchTaskProvider(data, (), tmp_path / "run", community=True, repository_guidance=True)
    a, b = p.part("org__repo-1"), p.part("org__repo-1")
    assert a.specification == b.specification
    assert len(calls) == 1
    assert "SECRET" not in a.specification and "SECRET" not in str(calls)
    assert "pipefail" in a.specification and "60-second" in a.specification
    assert "Ignored files" in a.specification
    assert p._preflight("org__repo-1")["image_id"] == "test"
    # A resumed provider must check again; no stale success trusted from disk.
    p2 = SWEbenchTaskProvider(data, (), tmp_path / "run", repository_guidance=True)
    p2._preflight("org__repo-1")
    assert len(calls) == 2


@pytest.mark.parametrize("script,expected", [("false | tail -1", 1), ("printf ok | tail -1", 0)])
def test_real_shell_pipeline_exit_survives_output_filter(
    script, expected, monkeypatch, docker_stub
):
    from tasks.swebench import pilot

    def capture(container, argv, timeout):
        assert argv[:2] == ["bash", "-lc"]
        assert "set -o pipefail;" in argv[2]
        shell = argv[2].replace(
            "source /opt/miniconda3/bin/activate testbed && cd /testbed && ", ""
        )
        r = subprocess.run(["bash", "-c", shell], capture_output=True, timeout=timeout)
        return SimpleNamespace(exit_code=r.returncode, output=r.stdout + r.stderr)

    monkeypatch.setattr(pilot, "captured_exec", capture)
    assert execute("container", script, 5)["exit_code"] == expected


def test_failed_preflight_does_not_return_a_task_or_cache_success(tmp_path, monkeypatch):
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                dict(
                    instance_id="org__repo-1",
                    repo="org/repo",
                    base_commit="base",
                    problem_statement="Repair it",
                )
            ]
        )
    )
    p = SWEbenchTaskProvider(data, (), tmp_path / "run", repository_guidance=True)

    def fail(*args):
        raise preflight.EnvironmentPreflightError("Missing test launcher")

    monkeypatch.setattr(preflight, "inspect_environment", fail)
    with pytest.raises(preflight.EnvironmentPreflightError, match="Missing test launcher"):
        p.part("org__repo-1")
    assert p.preflights == {}


def test_unavailable_docker_is_recorded_as_environment_failure(tmp_path, monkeypatch):
    def unavailable():
        raise RuntimeError("Docker unavailable")

    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=unavailable))
    with pytest.raises(preflight.EnvironmentPreflightError, match="Docker unavailable"):
        preflight.inspect_environment("org__repo-1", "org/repo", "base", tmp_path)
    report = json.loads((tmp_path / "org__repo-1.json").read_text())
    assert report["status"] == "failed" and "Docker unavailable" in report["error"]


def test_cli_preflights_first_draw_without_model_or_experiment(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    import yaml

    cfg = yaml.safe_load(Path("experiments/configs/community/lite.yaml").read_text())
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                dict(
                    instance_id=f"org__repo-{i}",
                    repo="org/repo",
                    base_commit="base",
                    problem_statement="Repair it",
                )
                for i in range(10)
            ]
        )
    )
    cfg["tasks"]["bank"] = str(data)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg))
    out = tmp_path / "check"
    seen = []

    def inspect(*args):
        seen.append(args[0])
        return {"guide": "Verified launcher", "image_id": "test"}

    monkeypatch.setattr(preflight, "inspect_environment", inspect)
    monkeypatch.setattr(
        preflight, "inspect_evaluation_environment", lambda *a: {"image_id": "test"}
    )
    monkeypatch.setattr(sys, "argv", ["preflight", str(config), "--seed", "0", "--out", str(out)])
    preflight.main()
    assert len(seen) == len(set(seen)) == 7
    assert "Preflight passed for 7" in capsys.readouterr().out
    assert not (out / "manifest.json").exists()
    assert not (out / "agents").exists()


def test_work_guide_is_public_repeatable_and_uses_correct_test_labels(tmp_path):
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                dict(
                    instance_id="django__django-1",
                    repo="django/django",
                    patch="HIDDEN_GOLD",
                    test_patch="HIDDEN_TESTS",
                )
            ]
        )
    )
    provider = SWEbenchTaskProvider(data, (), tmp_path / "run", community=True)
    from core.environment import Part

    guide = provider.work_guide(
        Part(
            title="Issue",
            specification="Public",
            reward=60,
            deadline_days=2,
            reference="django__django-1",
        )
    )
    assert "python tests/runtests.py --settings=test_sqlite" in guide
    assert "backends.base.test_operations" in guide
    assert "a source module under django/ is not a test label" in guide
    assert "read failures" in guide.lower()
    assert "WORKTREE" in guide and "private workspaces" in guide
    assert "HIDDEN" not in guide
    assert (
        provider.work_guide(
            Part(
                title="Issue",
                specification="Public",
                reward=60,
                deadline_days=2,
                reference="django__django-1",
            )
        )
        == guide
    )


def test_official_readiness_uses_strict_spec_and_existing_image_only(tmp_path, monkeypatch):
    from tasks.swebench import environment_spec

    cache = tmp_path / "http.json"
    cache.write_text("{}")
    spec = dict(instance="org__repo-1", image="swebench/exact:latest", status="passed")
    monkeypatch.setattr(environment_spec, "inspect_spec", lambda row, path: spec.copy())
    seen = []
    client = SimpleNamespace(
        images=SimpleNamespace(
            get=lambda name: (seen.append(name) or SimpleNamespace(id="sha256:exact"))
        ),
        close=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: client))
    report = preflight.inspect_evaluation_environment(
        {"instance_id": "org__repo-1"}, cache, tmp_path
    )
    assert report["image_id"] == "sha256:exact" and seen == ["swebench/exact:latest"]


def test_failed_offline_readiness_blocks_publication_even_without_work_guide(tmp_path, monkeypatch):
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps([dict(instance_id="org__repo-1", repo="org/repo", base_commit="base")])
    )
    provider = SWEbenchTaskProvider(
        data,
        (),
        tmp_path / "run",
        community=True,
        strict_http_cache=True,
        evaluation_preflight=True,
    )

    def unavailable(*args):
        raise preflight.EnvironmentPreflightError("missing official requirements cache")

    monkeypatch.setattr(preflight, "inspect_evaluation_environment", unavailable)
    with pytest.raises(preflight.EnvironmentPreflightError, match="requirements cache"):
        provider.sample_available(__import__("random").Random(0), 1, [])
    assert provider.preflights == {}
