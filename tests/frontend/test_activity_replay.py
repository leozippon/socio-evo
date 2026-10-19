"""Independent activity and shared-issue replay regression checks."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_activity_shared_deliverables_and_deadline_replay():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("activity_check.mjs"))],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_whole_second_clock_and_activity_timeline():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("activity_timeline_check.mjs"))],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
