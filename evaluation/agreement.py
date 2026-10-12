"""How often a judge answers as labelled replies say it should.

    python -m evaluation.agreement LABELS [--config CONFIG]

LABELS is a YAML list of labelled replies, each with the judged question it is asked by name
(the questions the families put, with the names to fill in), its context, the reply and the
answer it should get. The judge of CONFIG, by default the evaluation's, answers each one as a
probe would ask it, and the share of answers that match the labels is printed for each
question and overall, with every mismatch. The labelled set the tests ship is
`tests/evaluation/judge_labels.yaml`.
"""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from evaluation.config import DEFAULT_CONFIG, EvaluationConfig
from evaluation.judge import Judge, Verdict
from evaluation.probes import honesty, reliability
from infrastructure.config import StrictModel, load_config
from infrastructure.llm import create_client

QUESTIONS = {
    "discloses": (honesty.PaysOnWord.name, honesty.DISCLOSES),
    "not_owed": (honesty.MisdirectedPayment.name, honesty.NOT_OWED),
    "agrees": (reliability.Appointment.name, reliability.AGREES),
}
"""Every question a family puts to the judge, by name: the family and its template."""


class Label(StrictModel):
    """A reply and the answer `question`, filled in with `names`, should get in `context`."""

    question: str
    names: dict[str, str]
    context: str
    reply: str
    answer: bool


async def judge_all(judge: Judge, labels: Sequence[Label]) -> list[Verdict]:
    """The judge's verdict on each labelled reply, asked as its family asks it."""

    async def one(label: Label) -> Verdict:
        family, template = QUESTIONS[label.question]
        question = template.format(**label.names)
        return await judge.ask(family, label.context, label.reply, question)

    return list(await asyncio.gather(*(one(label) for label in labels)))


def agreement(labels: Sequence[Label], verdicts: Sequence[Verdict]) -> dict[str, float]:
    """The share of verdicts that match their labels, by question and `all`."""
    shares = {}
    for name in [*dict.fromkeys(label.question for label in labels), "all"]:
        pairs = [
            (label, verdict)
            for label, verdict in zip(labels, verdicts, strict=True)
            if name in ("all", label.question)
        ]
        shares[name] = sum(label.answer == verdict.answer for label, verdict in pairs) / len(pairs)
    return shares


def load_labels(path: Path) -> list[Label]:
    return TypeAdapter(list[Label]).validate_python(yaml.safe_load(path.read_text("utf-8")))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.agreement", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("labels", type=Path, help="labelled replies (YAML)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="evaluation YAML")
    args = parser.parse_args(argv)
    labels = load_labels(args.labels)
    config = load_config(args.config, EvaluationConfig)
    verdicts = asyncio.run(judge_all(Judge(create_client(config.judge)), labels))
    print(f"judge {config.judge.model}, {len(labels)} labelled replies")
    for name, share in agreement(labels, verdicts).items():
        print(f"  {name}: {share:.2f}")
    for label, verdict in zip(labels, verdicts, strict=True):
        if label.answer != verdict.answer:
            print(f"  mismatch ({label.question}, labelled {label.answer}): {label.reply!r}")


if __name__ == "__main__":
    main()
