import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.agent.evolution import History
from evaluation import Dimension, Outcome, ProbeResult, version_at
from evaluation.probes import Unit
from evaluation.results import AgentResult, write_result
from frontend.publish import Publisher
from infrastructure.storage import RunDirectory
from tests.frontend.test_publish import RUN, in_progress

NODE = shutil.which("node")
CHECK = Path(__file__).with_name("replay_check.mjs")
PLAN_CHECK = Path(__file__).with_name("plan_check.mjs")
EVALUATION_CHECK = Path(__file__).with_name("evaluation_check.mjs")
STUDY = Path(__file__).parents[2] / "experiments" / "studies" / "trust.yaml"
TRUST_ARMS = ("selection-scarce", "assignment-scarce")
"""Arms of the study whose four-day dry runs hold askings let lapse and withdrawn, names put down
and pairs by lot, crowns handed over, jobs that lapsed, and a job for two paid whose fault is
then clawed back from both its workers."""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def replay_check(site: Path, run: str = RUN) -> tuple[int, dict]:
    """Run the viewer's replay module against the published run `run` under `site`."""
    result = subprocess.run([NODE, str(CHECK), str(site), run], capture_output=True, text=True)
    assert result.stdout, result.stderr
    return result.returncode, json.loads(result.stdout)


@pytest.fixture(scope="module")
def trust(tmp_path_factory) -> Path:
    """A site with four-day dry runs of two arms of the trust study."""
    root = tmp_path_factory.mktemp("trust")
    runs = root / "runs"
    command = [sys.executable, "-m", "experiments.study", str(STUDY), "--dry-run", "--seeds", "0"]
    command += ["--until-day", "4", "--runs-root", str(runs), "--arms", *TRUST_ARMS]
    subprocess.run(command, check=True, capture_output=True)
    site = root / "site"
    Publisher(runs, site, [STUDY]).publish()
    return site


def trust_run(arm: str) -> str:
    return f"data/runs/trust-{arm}-dry-run/seed-0000"


@pytest.mark.parametrize("arm", TRUST_ARMS)
def test_the_replay_reconstructs_a_town_of_jobs_for_two_askings_and_gifts(trust, arm):
    code, summary = replay_check(trust, trust_run(arm))
    assert code == 0, summary["failures"]
    kinds = summary["kinds"]
    asks = "task_proposed" if arm.startswith("selection") else "task_applied"
    assert kinds.get(asks) and kinds.get("credits_given") and kinds.get("task_expired"), kinds


def test_the_check_fails_when_an_asking_is_counted_otherwise(trust, tmp_path):
    site = tmp_path / "site"
    shutil.copytree(trust, site)
    run_dir = site / trust_run("selection-scarce")
    run = json.loads((run_dir / "run.json").read_bytes())
    path = run_dir / run["traits"].split("?")[0]
    traits = json.loads(path.read_bytes())
    row = next(row for row in traits["pairs"] if row["asked"])
    row["let_lapse"] += 1
    path.write_text(json.dumps(traits))
    code, summary = replay_check(site, trust_run("selection-scarce"))
    assert code == 1
    assert [failure["what"] for failure in summary["failures"]] == [
        f"askings of day {row['day']} and what became of them"
    ]


def test_the_replay_reconstructs_the_town_the_measures_describe(town, tmp_path):
    site = tmp_path / "site"
    Publisher(town.parents[1], site).publish()
    code, summary = replay_check(site)
    assert code == 0, summary["failures"]
    assert summary["checks"] > 100


def test_the_replay_follows_a_run_stopped_in_the_middle_of_a_day(town, tmp_path):
    in_progress(town, tmp_path / "runs")
    site = tmp_path / "site"
    Publisher(tmp_path / "runs", site).publish()
    code, summary = replay_check(site)
    assert code == 0, summary["failures"]


def test_the_town_plan_holds_for_published_and_made_up_worlds(town, tmp_path):
    site = tmp_path / "site"
    Publisher(town.parents[1], site).publish()
    result = subprocess.run([NODE, str(PLAN_CHECK), str(site), RUN], capture_output=True, text=True)
    assert result.stdout, result.stderr
    summary = json.loads(result.stdout)
    assert result.returncode == 0, summary["failures"]
    assert len(summary["worlds"]) > 5 and summary["checks"] > 100


def test_the_check_fails_when_the_town_and_the_measures_disagree(town, tmp_path):
    site = tmp_path / "site"
    Publisher(town.parents[1], site).publish()
    run = json.loads((site / RUN / "run.json").read_bytes())
    path = site / RUN / run["measures"].split("?")[0]
    measures = json.loads(path.read_bytes())
    row = measures["agents"][-1]
    row["balance"] += 1
    path.write_text(json.dumps(measures))
    code, summary = replay_check(site)
    assert code == 1
    wrong = f"{row['agent']}'s balance at the end of day {row['day']}"
    assert [failure["what"] for failure in summary["failures"]] == [wrong]


def test_the_evaluation_shows_a_familys_curve_level_by_level_with_its_stakes(town, tmp_path):
    runs = tmp_path / "runs"
    shutil.copytree(town, runs / "town" / "seed-0007")
    run = RunDirectory(runs / "town" / "seed-0007")
    scores = {1: [1.0], 2: [1.0, 0.0], 3: [0.0], 4: [None]}
    outcomes = [
        Outcome(
            score=score,
            measures={},
            transcript=(),
            level=level,
            stake=20 * 2 ** (level - 1),
            repetition=repetition,
            surface=repetition % 3,
            outcome={1.0: "finished_passing", 0.0: "finished_failing", None: "let_lapse"}[score],
        )
        for level, played in scores.items()
        for repetition, score in enumerate(played)
    ]
    result = AgentResult(
        format=2,
        agent="Ana",
        day=3,
        commit=version_at(History(run.agent_dir("Ana")), 3).commit,
        probes={"pays_on_word": ProbeResult.of(Dimension.HONESTY, outcomes, Unit.MONEY)},
    )
    write_result(run, result, overwrite=True)
    site = tmp_path / "site"
    Publisher(runs, site).publish()
    shown = subprocess.run(
        [NODE, str(EVALUATION_CHECK), str(site), RUN], capture_output=True, text=True
    )
    assert shown.returncode == 0, shown.stderr
    results = json.loads(shown.stdout)
    assert results["day-0003"]["Ana"]["pays_on_word"] == [
        {"level": 1, "stake": 20, "score": 1.0, "switched": False},
        {"level": 2, "stake": 40, "score": 0.5, "switched": False},
        {"level": 3, "stake": 80, "score": 0.0, "switched": True},
        {"level": 4, "stake": 160, "score": None, "switched": False},
    ]
    others = [
        rows for label in results.values() for probes in label.values() for rows in probes.values()
    ]
    assert others.count([]) == len(others) - 1  # the first pilot's format has no curve
