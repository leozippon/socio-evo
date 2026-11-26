"""The operations scripts, run on copies of them in a scratch tree, never on runs/: ops/stop.sh
signals only the run's own process, ops/evaluate.sh starts both benchmarks of a day, and
ops/evaluate-queue.sh starts each day once its adapters are final and the day before has been
evaluated."""

from __future__ import annotations

import json
import os
import shutil
import signal
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
"""
"""A stand-in for the interpreter: it notes each module run with its arguments."""


def test_evaluate_starts_both_benchmarks_of_the_day(tmp_path):
    evaluate = copied(tmp_path, "evaluate.sh")
    (tmp_path / ".env").write_text("")
    stub = tmp_path / "python"
    stub.write_text(STUB)
    stub.chmod(0o755)
    calls = tmp_path / "calls"
    env = os.environ | {"PYTHON": str(stub), "CALLS": str(calls)}
    for day, told in (("07", 7), ("0", 0)):
        calls.write_text("")
        done = subprocess.run(
            [evaluate, "c", day], env=env | {"CONCURRENCY": "5"}, capture_output=True, text=True,
            timeout=10,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        assert done.stdout.splitlines() == [
            f"{benchmark}: log runs/eval-logs/c-day-{told:02d}-{benchmark}.log"
            for benchmark in ("safety", "mask")
        ]
        expected = sorted(
            f"-m evaluation.{benchmark} --run runs/c --day {told} --concurrency 5"
            for benchmark in ("safety", "mask")
        )
        deadline = time.monotonic() + 10  # detached: wait for both
        while sorted(calls.read_text().splitlines()) != expected:
            assert time.monotonic() < deadline, calls.read_text()
            time.sleep(0.05)
    refused = subprocess.run([evaluate, "c"], env=env, capture_output=True, text=True, timeout=10)
    assert refused.returncode == 2


QUEUE_STUB = """#!/usr/bin/env bash
if [[ $1 == -c ]]; then exec "$REAL" "$@"; fi
echo "$*" >> "$CALLS"
printf -v dd 'day-%02d' "$6"
while [[ -e $HELD/$dd ]]; do sleep 0.05; done
"""
"""A stand-in for the interpreter: it reads the manifest as Python does, notes each module run,
and evaluates a day for as long as a file named for the day is held."""


def test_evaluate_queue_waits_for_final_adapters_and_the_days_before(tmp_path):
    queue = copied(tmp_path, "evaluate-queue.sh")
    copied(tmp_path, "evaluate.sh")  # the real one, whose processes the queue must see
    (tmp_path / ".env").write_text("")
    stub = tmp_path / "python"
    stub.write_text(QUEUE_STUB)
    stub.chmod(0o755)
    calls, held = tmp_path / "calls", tmp_path / "held"
    calls.write_text("")
    held.mkdir()
    (held / "day-07").touch()
    run = tmp_path / "runs" / "q"
    (run / "checkpoints").mkdir(parents=True)
    manifest = run / "manifest.json"
    manifest.write_text(json.dumps({"status": "running"}))
    env = os.environ | {
        "PYTHON": str(stub),
        "REAL": sys.executable,
        "CALLS": str(calls),
        "HELD": str(held),
        "POLL": "0.1",
    }

    def called(text: str) -> list[str]:
        return [line for line in calls.read_text().splitlines() if text in line]

    def until(condition) -> None:
        deadline = time.monotonic() + 10
        while not condition():
            assert time.monotonic() < deadline
            time.sleep(0.05)

    following = subprocess.Popen(
        [queue, "q", "0", "7", "14", "21"],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,  # its group, killed if the test fails
    )
    try:
        until(lambda: len(called("--day 0 ")) == 2)  # the base model at once
        (run / "checkpoints" / "day-07.json").write_text("{}")
        (run / "learning" / "night-07").mkdir(parents=True)
        time.sleep(0.5)
        assert not called("--day 7 ")  # day 7's adapters are fitted in the night after it
        (run / "learning" / "night-07" / "done.json").write_text("{}")  # the night is complete
        until(lambda: len(called("--day 7 ")) == 2)
        assert all("--concurrency 16" in line for line in called("--day 7 "))  # the run lives
        (run / "checkpoints" / "day-14.json").write_text("{}")
        (run / "checkpoints" / "day-15.json").write_text("{}")  # night 14 is over too
        time.sleep(0.5)
        assert not called("--day 14 ")  # day 7 is still being evaluated

        manifest.write_text(json.dumps({"status": "interrupted"}))  # ended without day 21
        (held / "day-07").unlink()
        out, _ = following.communicate(timeout=10)
        assert following.returncode == 1
        day14 = called("--day 14 ")
        assert len(day14) == 2 and all("--concurrency 48" in line for line in day14)
        assert not called("--day 21")
        told = [line.split(" ", 2)[2] for line in out.splitlines() if line[:1].isdigit()]
        assert told == [
            "starting the day-0 evaluation with 16 in flight a benchmark",
            "starting the day-7 evaluation with 16 in flight a benchmark",
            "starting the day-14 evaluation with 48 in flight a benchmark",
            "the run is interrupted without day-21; the day-21 evaluation not started",
        ]
    finally:
        for hold in held.iterdir():
            hold.unlink()
        if following.poll() is None:
            os.killpg(following.pid, signal.SIGKILL)
            following.wait()
