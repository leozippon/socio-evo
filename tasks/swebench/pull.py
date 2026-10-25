"""Pull the task images of the splits from ghcr.io, resuming where an earlier pull stopped.

python -m tasks.swebench.pull [--split train|eval] [--workers N]
"""

import argparse
from collections.abc import Sequence

from tasks.swebench.dataset import SIZES, load_split
from tasks.swebench.images import pull


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=sorted(SIZES), help="only this split (default both)")
    parser.add_argument("--workers", type=int, default=8, help="parallel pulls (default 8)")
    args = parser.parse_args(argv)
    splits = [args.split] if args.split else list(SIZES)
    pull([task.image for split in splits for task in load_split(split)], workers=args.workers)


if __name__ == "__main__":
    main()
