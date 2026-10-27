"""Pull the task images of the splits from ghcr.io and accept every task's gold patch in its image.

python -m tasks.swebench.pull [--split train|eval] [--pulls N] [--acceptances N]

Images already on this machine are not pulled again, and a stopped pull resumes. Each outcome is
recorded in gold.json as it comes: an image that could not be pulled, and for every pulled task
`resolved` or why its gold patch was not. A task recorded as resolved is not accepted again, so a
stopped check resumes too. A failure does not stop the others: every image is tried and every
pulled task not yet resolved accepted, and the failures are listed at the end, after which the
command exits with an error; `python -m tasks.swebench.dataset` then redraws the splits without
the tasks recorded as failed. An acceptance that raises, as when Docker fails, is listed but not
recorded, so that the next pull checks its task again.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from datetime import date
from typing import get_args

from tasks.swebench.acceptance import accept
from tasks.swebench.dataset import GOLD, RESOLVED, Split, Task, load_gold, load_split
from tasks.swebench.images import pull

GOLD_TIMEOUT_S = 1800
_SOURCE = f"python -m tasks.swebench.pull, {date.today().isoformat()}"


def main(argv: Sequence[str] | None = None) -> None:
    splits = get_args(Split)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=splits, help="only this split (default both)")
    parser.add_argument("--pulls", type=int, default=8, help="parallel pulls (default 8)")
    parser.add_argument(
        "--acceptances", type=int, default=8, help="parallel acceptances (default 8)"
    )
    args = parser.parse_args(argv)
    chosen = [args.split] if args.split else splits
    tasks = [task for split in chosen for task in load_split(split)]
    failed = pull([task.image for task in tasks], workers=args.pulls)
    gold = load_gold()
    for task in tasks:
        if task.image in failed:
            gold[task.instance_id] = (
                f"its image could not be pulled: {failed[task.image]} ({_SOURCE})"
            )
    save_gold(gold)
    unchecked = [t for t in tasks if t.image not in failed and gold.get(t.instance_id) != RESOLVED]
    unresolved = asyncio.run(check_gold(unchecked, args.acceptances, gold))
    if failed or unresolved:
        lines = [f"  not pulled: {image}: {error}" for image, error in failed.items()]
        lines += [f"  gold not resolved: {instance}: {why}" for instance, why in unresolved.items()]
        raise SystemExit(
            f"{len(failed) + len(unresolved)} failures, recorded in {GOLD.name} unless an "
            "acceptance raised; python -m tasks.swebench.dataset redraws the splits without "
            "them:\n" + "\n".join(lines)
        )


async def check_gold(tasks: Sequence[Task], workers: int, gold: dict[str, str]) -> dict[str, str]:
    """Accept the gold patch of every task, `workers` at a time, printing progress and recording
    each outcome in `gold` and gold.json as it comes; returns why each task whose gold patch was
    not resolved was not, including an acceptance that raised, which is not recorded."""
    gate = asyncio.Semaphore(max(1, workers))
    started = time.monotonic()

    async def one(task: Task) -> tuple[Task, str | None, bool]:
        async with gate:
            try:
                verdict = await accept(task, task.patch, GOLD_TIMEOUT_S)
            except Exception as error:  # one task's failure must not stop the others
                return task, f"acceptance raised {type(error).__name__}: {error}", False
        if verdict.resolved:
            return task, None, True
        (passed, total), (kept, before) = verdict.fail_to_pass, verdict.pass_to_pass
        why = (
            f"the gold patch is not resolved in its image: {verdict.status}, {passed}/{total} "
            f"FAIL_TO_PASS and {kept}/{before} PASS_TO_PASS tests pass ({_SOURCE})"
        )
        return task, why, True

    print(f"accepting the gold patches of {len(tasks)} tasks")
    unresolved: dict[str, str] = {}
    for done, result in enumerate(asyncio.as_completed([one(task) for task in tasks]), 1):
        task, why, graded = await result
        if why is not None:
            unresolved[task.instance_id] = why
        if graded:
            gold[task.instance_id] = RESOLVED if why is None else why
            save_gold(gold)
        minutes = (time.monotonic() - started) / 60
        outcome = "resolved" if why is None else f"NOT RESOLVED ({why})"
        print(f"[{done}/{len(tasks)}, {minutes:.1f} min] {outcome} {task.instance_id}", flush=True)
    return dict(sorted(unresolved.items()))


def save_gold(gold: dict[str, str]) -> None:
    """Write the record of gold checks, sorted, replacing gold.json in one step."""
    written = GOLD.with_suffix(".json.tmp")
    written.write_text(json.dumps(dict(sorted(gold.items())), indent=2) + "\n")
    written.replace(GOLD)


if __name__ == "__main__":
    main()
