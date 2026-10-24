"""Accept a patch for a task officially and print the verdict as JSON.

    python -m tasks.swebench.accept <instance_id> <patch_file> [--timeout SECONDS]
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from tasks.swebench.acceptance import accept
from tasks.swebench.dataset import load_tasks


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instance_id")
    parser.add_argument("patch_file", type=Path)
    parser.add_argument("--timeout", type=int, default=1800, help="eval seconds (default 1800)")
    args = parser.parse_args(argv)
    task = load_tasks()[args.instance_id]
    verdict = asyncio.run(accept(task, args.patch_file.read_text(), args.timeout))
    print(verdict.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
