import json
import shutil
import subprocess
from pathlib import Path

import pytest

from frontend.publish import Publisher
from tests.frontend.test_publish import RUN, in_progress

NODE = shutil.which("node")
CHECK = Path(__file__).with_name("replay_check.mjs")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def replay_check(site: Path) -> tuple[int, dict]:
    """Run the viewer's replay module against the published run under `site`."""
    result = subprocess.run([NODE, str(CHECK), str(site), RUN], capture_output=True, text=True)
    assert result.stdout, result.stderr
    return result.returncode, json.loads(result.stdout)


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
