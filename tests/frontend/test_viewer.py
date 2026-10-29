"""The viewer under node and headless Chromium: the replay looks the town up in the published
timeline as the progress document counts it, also between whole seconds, and the town stands its
residents where the moment alone says; entries one resident alone knew of read so, a person's day
is what it perceived, and every move reads by its reason and where it happened; the town plan
holds for published and made-up worlds; and every route renders at a desktop and a phone width
without an error in the console or horizontal overflow."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from frontend.publish import Publisher
from tests.support.runs import RUN, make_run, write_results

NODE = shutil.which("node")
REPLAY_CHECK = Path(__file__).with_name("replay_check.mjs")
READING_CHECK = Path(__file__).with_name("reading_check.mjs")
PLAN_CHECK = Path(__file__).with_name("plan_check.mjs")
RENDER_CHECK = Path(__file__).with_name("render_check.mjs")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def site(tmp_path_factory) -> Path:
    """The town's run published with its evaluation results, beside a copy of it whose frozen
    configuration the publisher cannot read, so the home page has a run to list as not published."""
    root = tmp_path_factory.mktemp("viewer")
    run = await make_run(root / "runs")
    write_results(root / "results", "town")
    older = root / "runs" / "older"
    shutil.copytree(run.root, older)
    config = yaml.safe_load((older / "config.yaml").read_text())
    config["town"]["day"]["closing"] = "18:00"
    (older / "config.yaml").write_text(yaml.safe_dump(config))
    Publisher(root / "runs", root / "site", root / "results").publish()
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
    assert summary["clusters"] > 0  # residents standing together were laid out and compared


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


def test_entries_and_moves_read_as_the_residents_knew_them(site):
    result = subprocess.run(
        [NODE, str(READING_CHECK), str(site), RUN], capture_output=True, text=True
    )
    assert result.stdout, result.stderr
    summary = json.loads(result.stdout)
    assert result.returncode == 0, summary["failures"]
    assert summary["checks"] > 50


def test_the_town_plan_holds_for_published_and_made_up_worlds(site):
    result = subprocess.run([NODE, str(PLAN_CHECK), str(site), RUN], capture_output=True, text=True)
    assert result.stdout, result.stderr
    summary = json.loads(result.stdout)
    assert result.returncode == 0, summary["failures"]
    assert len(summary["worlds"]) > 5 and summary["checks"] > 100


def test_every_route_renders_without_errors_or_overflow_at_both_widths(site):
    result = subprocess.run(
        [NODE, str(RENDER_CHECK), str(site)], capture_output=True, text=True, timeout=900
    )
    assert result.stdout, result.stderr
    summary = json.loads(result.stdout)
    if result.returncode == 2:
        pytest.skip(summary["skipped"])
    assert result.returncode == 0, summary["failures"]
    assert summary["widths"] == 2 and summary["routes"] >= 20
