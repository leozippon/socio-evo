"""A resident's dataset: everything it has kept so far, as chat examples.

The dataset of a night is the examples of that night and every night before it, each moment once
(as it was first learnt), the newest `dataset_max` of them. `dataset.jsonl` holds one
`{"messages": [...]}` a line, all the trainer reads; `provenance.jsonl`, line for line, which
moment of which day each example is, the night it was kept, how it was chosen and what it was made
from (the run's `choice` and `examples`), and the reason the resident gave.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from infrastructure.storage import write_jsonl
from learning.generalise import Example

DATASET = "dataset.jsonl"
PROVENANCE = "provenance.jsonl"


def assemble(
    nights: Sequence[tuple[int, Sequence[Example]]], most: int
) -> list[tuple[int, Example]]:
    """The dataset of the examples of `nights`, each with its night, in the order of the nights:
    each moment once, the newest `most`."""
    seen: set[int] = set()
    chosen: list[tuple[int, Example]] = []
    for night, examples in nights:
        for example in examples:
            if example.moment not in seen:
                seen.add(example.moment)
                chosen.append((night, example))
    return chosen[-most:]


def write(folder: Path, dataset: Sequence[tuple[int, Example]], *, choice: str, made: str) -> None:
    """Write `dataset` into `folder` as `DATASET` and `PROVENANCE`."""
    write_jsonl(folder / DATASET, ({"messages": list(e.messages)} for _, e in dataset))
    write_jsonl(
        folder / PROVENANCE,
        (
            {
                "moment": e.moment,
                "day": e.day,
                "night": night,
                "choice": choice,
                "examples": made,
                "why": e.why,
            }
            for night, e in dataset
        ),
    )
