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

from tests.support.benchmarks import run_directory

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
if [[ $2 == "evaluation.${FAIL:-}" ]]; then exit 3; fi
"""
"""A stand-in for the interpreter: it notes each module run with its arguments, and fails the
benchmark FAIL names."""


def test_evaluate_runs_both_benchmarks_and_fails_when_either_does(tmp_path):
    evaluate = copied(tmp_path, "evaluate.sh")
    (tmp_path / ".env").write_text("")
    stub = tmp_path / "python"
    stub.write_text(STUB)
    stub.chmod(0o755)
    calls = tmp_path / "calls"
    env = os.environ | {"PYTHON": str(stub), "CALLS": str(calls), "CONCURRENCY": "5"}
    for day, told in (("07", 7), ("0", 0)):
        calls.write_text("")
        done = subprocess.run([evaluate, "c", day], env=env, capture_output=True, text=True,
                              timeout=10)  # fmt: skip
        assert done.returncode == 0, done.stderr
        assert done.stdout.splitlines() == [
            f"{benchmark}: log runs/eval-logs/c-day-{told:02d}-{benchmark}.log"
            for benchmark in ("safety", "mask")
        ]
        assert sorted(calls.read_text().splitlines()) == sorted(  # both ended before it did
            f"-m evaluation.{benchmark} --run runs/c --day {told} --concurrency 5"
            for benchmark in ("safety", "mask")
        )
    failed = subprocess.run([evaluate, "c", "7"], env=env | {"FAIL": "mask"}, capture_output=True,
                            text=True, timeout=10)  # fmt: skip
    assert failed.returncode == 1
    assert failed.stderr == "mask of c day-07 failed, see runs/eval-logs/c-day-07-mask.log\n"
    refused = subprocess.run([evaluate, "c"], env=env, capture_output=True, text=True, timeout=10)
    assert refused.returncode == 2


QUEUE_STUB = """#!/usr/bin/env bash
if [[ $1 == -c ]]; then exec "$REAL" "$@"; fi
echo "$*" >> "$CALLS"
printf -v dd 'day-%02d' "$6"
while [[ -e $HELD/$dd ]]; do sleep 0.05; done
if [[ $2 == evaluation.mask && $6 == "${FAIL_DAY:-}" ]]; then exit 3; fi
"""
"""A stand-in for the interpreter: Python itself for `-c` (the manifest, the run's configuration);
otherwise it notes each module run, evaluates a day for as long as a file named for the day is
held, and fails the MASK evaluation of day FAIL_DAY."""


def queued(tmp_path, *, learns: bool) -> tuple[Path, Path, dict, Path]:
    """A scratch tree with the queue, the real evaluate.sh, the stub and the run q."""
    copied(tmp_path, "evaluate.sh")  # the real one, which the queue waits for
    (tmp_path / ".env").write_text("")
    stub = tmp_path / "python"
    stub.write_text(QUEUE_STUB)
    stub.chmod(0o755)
    calls, held = tmp_path / "calls", tmp_path / "held"
    calls.write_text("")
    held.mkdir()
    run = run_directory(tmp_path, name="q", learns=learns)
    (run / "checkpoints").mkdir()
    (run / "manifest.json").write_text(json.dumps({"status": "running"}))
    env = os.environ | {
        "PYTHON": str(stub),
        "REAL": sys.executable,
        "CALLS": str(calls),
        "HELD": str(held),
        "POLL": "0.1",
    }
    return copied(tmp_path, "evaluate-queue.sh"), run, env, calls


def until(condition) -> None:
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_evaluate_queue_waits_for_complete_nights_and_tells_what_failed(tmp_path):
    queue, run, env, calls = queued(tmp_path, learns=True)
    held = Path(env["HELD"])
    (held / "day-07").touch()

    def called(text: str) -> list[str]:
        return [line for line in calls.read_text().splitlines() if text in line]

    following = subprocess.Popen(
        [queue, "q", "0", "7", "14", "21"],
        env=env | {"FAIL_DAY": "14"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # its group, killed if the test fails
    )
    try:
        until(lambda: len(called("--day 0 ")) == 2)  # the base model at once
        # The run saves a day's checkpoint before the night: no checkpoint, not even the next
        # day's, makes the day's adapters final.
        (run / "checkpoints" / "day-07.json").write_text("{}")
        (run / "checkpoints" / "day-08.json").write_text("{}")
        (run / "learning" / "night-07").mkdir(parents=True)
        time.sleep(0.5)
        assert not called("--day 7 ")
        (run / "learning" / "night-07" / "done.json").write_text("{}")  # the night is complete
        until(lambda: len(called("--day 7 ")) == 2)
        assert all("--concurrency 16" in line for line in called("--day 7 "))  # the run lives
        (run / "learning" / "night-14").mkdir(parents=True)
        (run / "learning" / "night-14" / "done.json").write_text("{}")
        time.sleep(0.5)
        assert not called("--day 14 ")  # day 7 is still being evaluated

        # The run ends after day 21's checkpoint, its night broken off.
        (run / "checkpoints" / "day-21.json").write_text("{}")
        (run / "manifest.json").write_text(json.dumps({"status": "failed"}))
        (held / "day-07").unlink()
        out, err = following.communicate(timeout=10)
        assert following.returncode == 1
        day14 = called("--day 14 ")
        assert len(day14) == 2 and all("--concurrency 48" in line for line in day14)
        assert not called("--day 21")
        told = [line.split(" ", 2)[2] for line in out.splitlines() if line[:1].isdigit()]
        assert told == [
            "starting the day-0 evaluation with 16 in flight a benchmark",
            "the day-0 evaluation finished",
            "starting the day-7 evaluation with 16 in flight a benchmark",
            "the day-7 evaluation finished",
            "starting the day-14 evaluation with 48 in flight a benchmark",
            "the day-14 evaluation failed",
            "the run is failed without runs/q/learning/night-21/done.json; the day-21 "
            "evaluation not started",
            "failed: days 14 21 (not started)",
        ]
        assert err == "mask of q day-14 failed, see runs/eval-logs/q-day-14-mask.log\n"
    finally:
        for hold in held.iterdir():
            hold.unlink()
        if following.poll() is None:
            os.killpg(following.pid, signal.SIGKILL)
            following.wait()


def test_evaluate_queue_scores_a_run_that_does_not_learn_after_its_checkpoints(tmp_path):
    queue, run, env, calls = queued(tmp_path, learns=False)
    following = subprocess.Popen(
        [queue, "q", "7"], env=env, stdout=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        time.sleep(0.5)
        assert calls.read_text() == ""
        (run / "checkpoints" / "day-07.json").write_text("{}")
        out, _ = following.communicate(timeout=10)
        assert following.returncode == 0, out
        assert len(calls.read_text().splitlines()) == 2
    finally:
        if following.poll() is None:
            os.killpg(following.pid, signal.SIGKILL)
            following.wait()
