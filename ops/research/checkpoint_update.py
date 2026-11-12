"""Apply a prepared checkout once the running research town saves its next full day.

Only the town is restarted. Its model supervisor is briefly held during maintenance
so that the model service stays alive. The complete pre-resume run is backed up.
"""

import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--watch", action="store_true", help="Omit for read-only preflight")
    args = parser.parse_args()
    root, code = args.root.resolve(), args.code.resolve()
    run = root / "runs" / args.run

    def manifest():
        return json.loads((run / "manifest.json").read_text())

    old = manifest()
    assert old["status"] == "running" and old["pid"], "Town must be running"
    town_pid = old["pid"]
    assert b"experiments.run" in Path(f"/proc/{town_pid}/cmdline").read_bytes()
    assert Path(f"/proc/{town_pid}/cwd").resolve() == root / "code"
    model = json.loads((root / "model-status.json").read_text())
    assert model["phase"] == "ready"
    supervisor = model["launcher_pid"]
    assert str(root).encode() in Path(f"/proc/{supervisor}/cmdline").read_bytes()
    revision = subprocess.check_output(
        ["git", "-C", str(code), "rev-parse", "HEAD"], text=True
    ).strip()
    assert not subprocess.check_output(["git", "-C", str(code), "status", "--porcelain"])
    checkpoints = run / "checkpoints"
    previous = max(checkpoints.glob("day-*.json"))
    from experiments.config import load_experiment
    from infrastructure.config import load_config
    from simulation.config import ExperimentConfig

    config = code / "experiments/configs/research-zenith.yaml"
    assert load_experiment(config) == load_config(run / "config.yaml", ExperimentConfig)
    state = dict(
        phase="waiting_for_checkpoint",
        old_pid=town_pid,
        revision=revision,
        previous_checkpoint=previous.name,
        prepared_at=datetime.now(UTC).isoformat(),
    )
    if not args.watch:
        print(json.dumps(state))
        return
    lock = (root / "checkpoint-update.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def status(**changes):
        state.update(changes, updated_at=datetime.now(UTC).isoformat())
        tmp = root / "checkpoint-update.tmp"
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(root / "checkpoint-update.json")

    held = town_held = False
    try:
        status()
        while True:
            current = manifest()
            if current["status"] != "running" or current["pid"] != town_pid:
                raise RuntimeError(
                    "Town stopped or changed before the checkpoint; no update applied"
                )
            checkpoint = max(checkpoints.glob("day-*.json"))
            if checkpoint > previous:
                break
            time.sleep(0.1)
        os.kill(supervisor, signal.SIGSTOP)
        held = True
        os.kill(town_pid, signal.SIGSTOP)
        town_held = True
        status(phase="switching", checkpoint=checkpoint.name)
        # Graceful cancellation, with no model or other deployment signalled.
        os.kill(town_pid, signal.SIGTERM)
        os.kill(town_pid, signal.SIGCONT)
        town_held = False
        deadline = time.monotonic() + 120
        while manifest()["pid"] is not None:
            if time.monotonic() > deadline:
                raise TimeoutError("Town did not stop; no forced termination or resume attempted")
            time.sleep(0.1)
        backup = root / "backups" / (checkpoint.stem + "-before-edit-fix")
        shutil.copytree(run, backup)
        status(backup=str(backup))
        log_offset = (run / "world.jsonl").stat().st_size
        env = os.environ.copy()
        env.update(
            VLLM_BASE_URL="http://127.0.0.1:8040/v1",
            VLLM_API_KEY=(root / "model-api-key").read_text().strip(),
            PYTHONUNBUFFERED="1",
        )
        with (root / "town.log").open("ab") as log:
            child = subprocess.Popen(
                [
                    str(root / "venv/bin/python"),
                    "-m",
                    "experiments.run",
                    str(config),
                    "--runs-root",
                    str(root / "runs"),
                    "--resume",
                ],
                cwd=code,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (root / "town.pid").write_text(str(child.pid))
        deadline = time.monotonic() + 180
        while True:
            if child.poll() is not None:
                raise RuntimeError(f"Resume exited with {child.returncode}; inspect town.log")
            current = manifest()
            log_text = (run / "run.log").read_text()
            with (run / "world.jsonl").open("rb") as world_log:
                world_log.seek(log_offset)
                data = world_log.read()
            resumed = any(
                json.loads(line).get("kind") == "resume"
                for line in data[: data.rfind(b"\n") + 1].splitlines()
            )
            if current["pid"] == child.pid and f"at {revision}" in log_text and resumed:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Resume not confirmed; inspect town.log")
            time.sleep(0.2)
        status(phase="applied", new_pid=child.pid, code=str(code))
    except BaseException as error:
        status(phase="failed", error=str(error))
        raise
    finally:
        if town_held:
            os.kill(town_pid, signal.SIGCONT)
        if held:
            os.kill(supervisor, signal.SIGCONT)
        lock.close()


if __name__ == "__main__":
    main()
