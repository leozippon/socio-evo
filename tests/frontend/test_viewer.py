"""The viewer's pure modules under node: the replay looks the town up in the published timeline
as the progress document counts it, and the town plan holds for published and made-up worlds."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

from frontend.publish import Publisher
from tests.frontend.test_publish import RUN, make_run

NODE = shutil.which("node")
REPLAY_CHECK = Path(__file__).with_name("replay_check.mjs")
PLAN_CHECK = Path(__file__).with_name("plan_check.mjs")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def site(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("viewer")
    await make_run(root / "runs")
    Publisher(root / "runs", root / "site").publish()
    return root / "site"


def replay_check(site: Path) -> tuple[int, dict]:
    result = subprocess.run(
        [NODE, str(REPLAY_CHECK), str(site), RUN], capture_output=True, text=True
    )
    assert result.stdout, result.stderr
    return result.returncode, json.loads(result.stdout)


def test_the_replay_looks_up_the_town_the_progress_counts(site):
    code, summary = replay_check(site)
    assert code == 0, summary["failures"]
    assert summary["checks"] > 60 and summary["days"] == 2


def test_the_check_fails_when_the_timeline_and_the_progress_disagree(site, tmp_path):
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    run = json.loads((copy / RUN / "run.json").read_bytes())
    path = copy / RUN / run["progress"].split("?")[0]
    progress = json.loads(path.read_bytes())
    progress["daily"][0]["purse"]["max"] += 1
    path.write_text(json.dumps(progress))
    code, summary = replay_check(copy)
    assert code == 1
    assert [failure["what"] for failure in summary["failures"]] == ["purses at the end of day 1"]


def test_the_town_plan_holds_for_published_and_made_up_worlds(site):
    result = subprocess.run([NODE, str(PLAN_CHECK), str(site), RUN], capture_output=True, text=True)
    assert result.stdout, result.stderr
    summary = json.loads(result.stdout)
    assert result.returncode == 0, summary["failures"]
    assert len(summary["worlds"]) > 5 and summary["checks"] > 100
