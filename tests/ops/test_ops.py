"""The operations scripts, run on copies of them in a scratch tree, never on runs/: ops/stop.sh
signals only the run's own process, and ops/evaluate.sh runs MASK only on its days and the
capability tasks only for the programmers and their leader."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RUN = """
import json, signal, sys, time
manifest, log = sys.argv[1:3]
held = open(log, "a")
def stop(*_):
    json.dump({"status": "interrupted", "pid": None}, open(manifest, "w"))
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
print("ready", flush=True)
while True:
    time.sleep(1)
"""
"""A stand-in for a run's process: its command line names experiments.run, it holds its run's
run.log open, and on SIGTERM it marks its manifest interrupted, as a run does."""


def copied(root: Path, script: str) -> Path:
    (root / "ops").mkdir(exist_ok=True)
    return Path(shutil.copy(ROOT / "ops" / script, root / "ops" / script))


def running(root: Path, run: str) -> subprocess.Popen[str]:
    directory = root / "runs" / run
    directory.mkdir(parents=True)
    manifest, log = directory / "manifest.json", directory / "run.log"
    process = subprocess.Popen(
        [sys.executable, "-c", RUN, str(manifest), str(log), "experiments.run"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None and process.stdout.readline() == "ready\n"
    manifest.write_text(json.dumps({"status": "running", "pid": process.pid}))
    return process


def test_stop_signals_the_runs_own_process_and_no_other(tmp_path):
    stop = copied(tmp_path, "stop.sh")
    env = os.environ | {"PYTHON": sys.executable}
    x, y = running(tmp_path, "x"), running(tmp_path, "y")
    try:
        manifest = tmp_path / "runs" / "x" / "manifest.json"
        recorded = json.loads(manifest.read_text())
        # Another run's process, as when x was killed outright and its pid reused, is refused.
        manifest.write_text(json.dumps({"status": "running", "pid": y.pid}))
        refused = subprocess.run([stop, "x"], env=env, capture_output=True, text=True, timeout=10)
        assert refused.returncode == 1 and y.poll() is None
        assert refused.stderr == (
            f"process {y.pid} in runs/x/manifest.json is not this run; nothing stopped\n"
        )
        manifest.write_text(json.dumps({"status": "interrupted", "pid": None}))
        refused = subprocess.run([stop, "x"], env=env, capture_output=True, text=True, timeout=10)
        assert refused.returncode == 1 and "records no process" in refused.stderr

        # Its own process is stopped, and the status it leaves is told.
        manifest.write_text(json.dumps(recorded))
        stopping = subprocess.Popen([stop, "x"], env=env, stdout=subprocess.PIPE, text=True)
        assert x.wait(timeout=10) == 0  # reaped here, so that stop.sh sees it end
        assert stopping.communicate(timeout=10)[0] == "x: interrupted\n"
        assert stopping.returncode == 0 and y.poll() is None
    finally:
        for process in (x, y):
            process.kill()
            process.wait()


STUB = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
if [[ $2 == evaluation.exports ]]; then
    printf '%s\\n' "Mei team-leader" "Jonas chef" "Aisha programmer"
fi
"""
"""A stand-in for the interpreter: it notes each module run, and lists the export as holding the
team leader, the chef and a programmer."""


def test_evaluate_runs_capability_for_the_programmers_and_mask_for_all_on_its_days(tmp_path):
    evaluate = copied(tmp_path, "evaluate.sh")
    (tmp_path / ".env").write_text("")
    stub = tmp_path / "python"
    stub.write_text(STUB)
    stub.chmod(0o755)
    calls = tmp_path / "calls"
    env = os.environ | {"PYTHON": str(stub), "CALLS": str(calls)}
    chains = {
        7: {"Mei": ["capability"], "Jonas": [], "Aisha": ["capability"]},
        14: {"Mei": ["mask", "capability"], "Jonas": ["mask"], "Aisha": ["mask", "capability"]},
    }
    for day, chain in chains.items():
        calls.write_text("")
        told = subprocess.run(
            [evaluate, "c", str(day)], env=env, capture_output=True, text=True, timeout=10
        )
        assert told.returncode == 0, told.stderr
        logs = f"logs runs/eval-logs/day-{day:02d}"
        assert told.stdout.splitlines() == [
            f"{r}: {' then '.join(run)}, {logs}-{r}-*.log" if run else f"{r}: nothing on this day"
            for r, run in chain.items()
        ]
        export = f"exports/c/day-{day:02d}"
        expected = ["experiments.export runs/c", f"evaluation.exports {export}"]
        expected += [
            f"evaluation.{module} {export}/{r}" for r, run in chain.items() for module in run
        ]
        deadline = time.monotonic() + 10  # the chains run detached: wait for them to finish
        while len(calls.read_text().splitlines()) < len(expected):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        time.sleep(0.2)  # and for any call that should not come
        modules = [" ".join(line.split()[1:3]) for line in calls.read_text().splitlines()]
        assert sorted(modules) == sorted(expected)
    assert not (tmp_path / "results" / "c" / "day-07" / "mask").exists()
