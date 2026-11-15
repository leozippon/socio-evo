"""Single-lab launch retains real preflight, frozen settings and resume checks."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
import yaml

from experiments.config import load_experiment
from infrastructure.config import ConfigError
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


def test_institute_has_four_phd_peers_and_recurring_funded_reviews(monkeypatch):
    for key in ("VLLM_API_KEY", "LIGHTING_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    config = run_pair.configuration(
        run_pair.PROJECT_ROOT / "experiments/configs/ai-lab.yaml", 20260302, "device=1"
    )
    run_pair.require_credentials({"lab": config})
    research = config.town.research
    assert config.days == 70 and research.start_day == 8
    assert len(config.residents) == 4
    assert {resident.occupation for resident in config.town.residents} == {"student"}
    assert research.allowance == 1260 and not research.milestones
    assert research.review_style == "conference"
    assert [stage.day for stage in research.stages_through(91)] == [28, 49, 70, 91]
    assert all(stage.artifact == "paper.tex" for stage in research.stages_through(91))
    for resident in config.residents:
        background = (run_pair.PROJECT_ROOT / resident.background).read_text()
        assert "PhD student" in background
        assert not any(term in background for term in ("paper.tex", "day 8", "21 days"))


def test_ir_lab_keeps_free_week_and_separates_stipends_from_conferences(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "test-actor-key")
    monkeypatch.setenv("LIGHTING_API_KEY", "test-judge-key")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    config = run_pair.configuration(
        run_pair.PROJECT_ROOT / "experiments/configs/ir-lab.yaml", 20260302, "device=1"
    )
    run_pair.require_credentials({"lab": config})
    research = config.town.research
    assert config.town.start_date == date(2026, 3, 1)
    assert config.days == 306
    assert config.town.start_date + timedelta(days=config.days - 1) == date(2026, 12, 31)
    assert research.start_day == 8 and research.allowance == 1260
    assert research.stipend_per_resident == 630 and research.stipend_interval_days == 21
    assert research.pit and not research.network and not research.semantic_scholar
    assert research.cycles is None and not research.milestones and research.conferences
    assert research.stages_through(config.days) == ()
    assert "Beijing Zhongguancun Academy" in research.institution
    assert "2503.09516v5" in research.background
    assert "2504.03160v4" in research.background
    assert "2504.21776v2" in research.background
    for resident in config.residents:
        background = resident.background_path.read_text()
        assert "PhD student" in background and "Beijing Zhongguancun Academy" in background
        assert not any(term in background.lower() for term in (
            "day 8", "deadline", "conference", "paper.tex", "submission", "21 days",
        ))


def test_research_resources_resolve_at_declaration_and_freeze_as_contents(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "reading.md").write_text("# Public reading\nA dated primary source.\n")
    (base / "conferences.yaml").write_text("[]\n")
    (base / "profile.yaml").write_text(
        f"base: {run_pair.PROJECT_ROOT / 'experiments/configs/ai-lab.yaml'}\n"
        "research_background: reading.md\nconference_calendar: conferences.yaml\n"
        "town: {research: {cycles: null}}\n"
    )
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("base: base/profile.yaml\nname: resource-test\n")
    config = load_experiment(overlay)
    assert config.town.research.background == "# Public reading\nA dated primary source.\n"
    assert config.town.research.conferences == ()
    frozen = tmp_path / "frozen.yaml"
    frozen.write_text(yaml.safe_dump(config.model_dump(mode="json")))
    (base / "reading.md").unlink()
    (base / "conferences.yaml").unlink()
    assert load_experiment(frozen) == config
    with pytest.raises(ConfigError, match="cannot load research_background"):
        load_experiment(overlay)


def test_research_resource_conflicts_and_invalid_calendars_fail_explicitly(tmp_path):
    reading = tmp_path / "reading.md"
    reading.write_text("Public reading")
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        f"base: {run_pair.PROJECT_ROOT / 'experiments/configs/ai-lab.yaml'}\n"
        "research_background: reading.md\ntown: {research: {background: duplicated}}\n"
    )
    with pytest.raises(ConfigError, match="use either research_background"):
        load_experiment(profile)
    (tmp_path / "invalid.yaml").write_text("conferences: []\n")
    profile.write_text("conference_calendar: invalid.yaml\n")
    with pytest.raises(ConfigError, match="must contain a list"):
        load_experiment(profile)


def test_pit_horizon_waits_for_real_dates_without_changing_frozen_config():
    config = run_pair.configuration(
        run_pair.PROJECT_ROOT / "experiments/configs/ir-lab.yaml", 19, "device=1"
    )
    now = datetime(2026, 11, 14, 20, 30, tzinfo=UTC)  # Beijing checkpoint, November 15.
    expected = (date(2026, 11, 15) - date(2026, 3, 1)).days
    assert run_lab.planned_until_day(config, None, now) == expected
    midnight = datetime(2026, 11, 14, 16, tzinfo=UTC)
    assert run_lab.planned_until_day(config, None, midnight) == expected - 1
    assert run_lab.planned_until_day(config, 70, now) == 70
    assert config.days == 306
    with pytest.raises(ValueError, match=f"from 1 to {expected}"):
        run_lab.planned_until_day(config, expected + 1, now)
    with pytest.raises(ValueError, match="No PIT checkpoint day"):
        run_lab.planned_until_day(config, None, datetime(2026, 3, 1, tzinfo=UTC))
    assert run_lab.planned_until_day(config, None, datetime(2027, 1, 1, tzinfo=UTC)) == 306


def test_pit_preflight_only_does_not_require_future_calendar_days(tmp_path, monkeypatch):
    monkeypatch.setattr(run_pair, "PROJECT_STORAGE", tmp_path)
    for key in ("VLLM_API_KEY", "LIGHTING_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Preflight-only must not plan or start an experiment")

    async def preflight(configs, control):
        assert configs["lab"].days == 306
        return {"ok": True}

    monkeypatch.setattr(run_lab, "planned_until_day", forbidden)
    monkeypatch.setattr(run_lab, "run", forbidden)
    monkeypatch.setattr(run_lab, "preflight", preflight)
    assert run_lab.main([
        "--runs-root", str(tmp_path / "runs"), "--config",
        str(run_pair.PROJECT_ROOT / "experiments/configs/ir-lab.yaml"),
        "--until-day", "306", "--preflight-only",
    ]) == 0
    assert not any((tmp_path / "runs").glob("*/manifest.json"))
