"""Fetch NuminaMath and convert a sample of it into calculation banks outside the repository.

    python -m tasks.calculation.fetch [--data-dir DIR]

The source is NuminaMath-1.5 (Hugging Face dataset `AI-MO/NuminaMath-1.5`, Apache-2.0) at a
pinned revision: its three parquet files, about 530 MB, are downloaded whole into
`DIR/numinamath/raw/` in the layout of `tasks.bank`, since only whole files can be checked
against their SHA-256, and read column by column with pyarrow, the project's `banks` extra. The
banks are written beside the raw files:

    pool/   a sample of the convertible problems
    town/   the town bank: the pool in the town mix (`tasks.bank.town`), whose preference
            for tasks at which calibration found an attempt that passed the visible checks
            and failed a hidden one never applies here: an answer passes the client's check
            exactly when it is right

Each task file is in the bank format of `tasks.calculation.provider`, named by a hash of its
problem, and the index records each task's origin.

Conversion keeps a problem whose `question_type` is a math word problem, whose
`problem_is_valid` and `solution_is_valid` are both "Yes", which is not synthetic, whose text
does not refer to a figure, is not in several parts (whose answer would answer only one) and
has at most `MAX_PROBLEM_CHARS` characters, whose `answer` can be read as one number
(`tasks.calculation.answers`), and which does not repeat an earlier problem word for word. Of
those, the `POOL_SIZE` first by hash of their name form the pool, so the sample depends on
nothing else. A problem's label follows its source, the collection it came from (`LABELS`):
school exercises are easy, curated contest collections medium, olympiad and forum problems
hard. Reward and deadline follow difficulty (`TERMS`).
"""

import argparse
import hashlib
import heapq
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from infrastructure.config import StrictModel
from tasks import bank
from tasks.bank import Difficulty, Dropped, Index, Problem, Trade, hashed
from tasks.calculation.answers import value
from tasks.calculation.provider import CalculationTask

SOURCE = "numinamath"
REPOSITORY = "AI-MO/NuminaMath-1.5"
REVISION = "1b05109f9e5c1ad06c0663519502416c30b300f8"
FILES = {
    "data/train-00000-of-00003.parquet": (
        "1e37cedcc5104c0d5a9afbf8b26328a59d7005cd37c2bd08352419f5f0e03214"
    ),
    "data/train-00001-of-00003.parquet": (
        "bc48fdddc1ab4e559727ad4f1f03b0263785c1c16b7964fb885fba07e18d6a39"
    ),
    "data/train-00002-of-00003.parquet": (
        "951aa899fe2a1b64f5b40c6636372d35b9db4f0b9c922e874d4bf357db64da66"
    ),
}
"""The source files at `REVISION` and their SHA-256."""

COLUMNS = (
    "problem",
    "answer",
    "problem_type",
    "question_type",
    "problem_is_valid",
    "solution_is_valid",
    "source",
    "synthetic",
)
POOL_SIZE = 3000
MAX_PROBLEM_CHARS = 2000

LABELS = {
    "cn_k12": Difficulty.EASY,
    "cn_contest": Difficulty.MEDIUM,
    "inequalities": Difficulty.MEDIUM,
    "number_theory": Difficulty.MEDIUM,
    "amc_aime": Difficulty.HARD,
    "aops_forum": Difficulty.HARD,
    "olympiads": Difficulty.HARD,
    "olympiads_ref": Difficulty.HARD,
}
"""The difficulty of a problem from each of NuminaMath's sources that is not synthetic."""

TERMS = {
    Difficulty.EASY: (20, 1),
    Difficulty.MEDIUM: (30, 1),
    Difficulty.HARD: (40, 2),
    Difficulty.UNSOLVED: (40, 2),
}
"""The reward and the deadline in days of a task of each difficulty."""

TITLES = {
    "Algebra": "An algebra problem",
    "Geometry": "A geometry problem",
    "Number Theory": "A number theory problem",
    "Combinatorics": "A counting problem",
    "Inequalities": "An inequality problem",
    "Logic and Puzzles": "A puzzle",
    "Calculus": "A calculus problem",
}
"""A task's title by the problem's type; any other type is just a problem."""

_FIGURE = re.compile(
    r"!\[|\[img\]|\[asy\]|\\includegraphics"  # an image, or a drawing in code
    r"|\b(?:fig|figure|diagram|picture|sketch)\b|\bfollowing (?:graph|shows)\b",  # one referred to
    re.IGNORECASE,
)
_SECOND_PART = re.compile(
    r"(?:^|[\s.;:,$(])[(（]\s*(?:II|Ⅱ|ii|2|b)\s*[)）]"  # (2), $(2)$, \((2)\), (II), (b)
    r"|^\s*[1a]\s*[.)、]\s.*^\s*[2b]\s*[.)、]\s"  # lines opening 1. then 2., or a) then b)
    r"|\[b\]\s*[2b]\s*[.)]",  # [b]b)[/b]
    re.MULTILINE | re.DOTALL,
)


class Origin(StrictModel):
    """The benchmark problem a task was made from: its source and type in NuminaMath."""

    source: str
    revision: str
    collection: str
    problem_type: str


class Entry(bank.Entry):
    """What the index says about one task: its difficulty and whether it was measured, and its
    origin."""

    origin: Origin


CalculationIndex = Index[Entry]
"""The `index.json` of a calculation bank."""


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tasks.calculation.fetch", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--data-dir", type=Path, default=bank.DATA_DIR)
    args = parser.parse_args(argv)
    root = args.data_dir.expanduser() / SOURCE
    raw = root / "raw"
    bank.download(raw, REPOSITORY, REVISION, FILES)
    problems, dropped = convert(records([raw / Path(name).name for name in FILES]))
    for reason, count in sorted(dropped.items()):
        print(f"dropped {count}: {reason}")
    results = bank.calibration(root)
    built = bank.build(root, Trade.CALCULATION, CalculationTask, TERMS, Entry, problems, results)
    bank.report(built, results)


def records(files: Sequence[Path]) -> Iterator[dict[str, Any]]:
    """The rows of the parquet `files`, with the columns of `COLUMNS` only."""
    import pyarrow.parquet

    for path in files:
        for batch in pyarrow.parquet.ParquetFile(path).iter_batches(columns=list(COLUMNS)):
            yield from batch.to_pylist()


def convert(rows: Iterable[Mapping[str, Any]]) -> tuple[list[Problem], Counter[str]]:
    """The pool: the `POOL_SIZE` convertible problems of `rows` first by hash of their name,
    in name order, and how many rows were dropped for each reason."""
    kept: list[tuple[float, str, Problem]] = []
    seen, dropped = set(), Counter()
    for row in rows:
        try:
            problem = convert_row(row)
        except Dropped as reason:
            dropped[str(reason)] += 1
            continue
        if problem.name in seen:
            dropped["it repeats an earlier problem"] += 1
            continue
        seen.add(problem.name)
        heapq.heappush(kept, (-hashed(problem.name), problem.name, problem))
        if len(kept) > POOL_SIZE:
            heapq.heappop(kept)
    dropped["outside the sample"] += len(seen) - len(kept)
    return sorted((problem for *_, problem in kept), key=lambda p: p.name), dropped


def convert_row(row: Mapping[str, Any]) -> Problem:
    """The task made from one source row; raises Dropped if there is none."""
    if row["question_type"] != "math-word-problem":
        raise Dropped("not a word problem")
    if row["problem_is_valid"] != "Yes" or row["solution_is_valid"] != "Yes":
        raise Dropped("the problem or its solution is not marked valid")
    if row["synthetic"]:
        raise Dropped("synthetic")
    if row["source"] not in LABELS:
        raise Dropped("a source without a label")
    problem = _statement(row["problem"])
    if _FIGURE.search(problem):
        raise Dropped("it refers to a figure")
    if _SECOND_PART.search(problem):
        raise Dropped("it has several parts")
    if len(problem) > MAX_PROBLEM_CHARS:
        raise Dropped(f"longer than {MAX_PROBLEM_CHARS} characters")
    answer = (row["answer"] or "").strip()
    if value(answer) is None:
        raise Dropped("the answer is not one number")
    label = LABELS[row["source"]]
    task = {
        "title": TITLES.get(row["problem_type"], "A problem"),
        "problem": problem,
        "answer": answer,
        "reward": TERMS[label][0],
        "deadline_days": TERMS[label][1],
    }
    origin = Origin(
        source=SOURCE,
        revision=REVISION,
        collection=row["source"],
        problem_type=row["problem_type"],
    )
    name = "numina-" + hashlib.sha256(problem.encode()).hexdigest()[:16]
    return Problem(name=name, task=task, origin=origin, label=label)


def _statement(text: str) -> str:
    """The problem with trailing spaces, carriage returns and runs of blank lines removed."""
    lines = (line.rstrip() for line in text.replace("\r", "").split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


if __name__ == "__main__":
    main()
