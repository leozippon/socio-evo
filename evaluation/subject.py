"""What the benchmarks are put to: the bare weights, in a plain conversation.

A subject is a served base model, alone or with one resident's LoRA adapter (`learning`). It is
asked nothing but the benchmark's own conversation: no background, no memory, no tools, no
system prompt of ours (a MASK scenario's system prompt is part of the scenario), at temperature 0
with a fixed token limit and the run's reasoning setting, one answer to each prompt. Reasoning
the server returns apart from the answer is kept with it and never taken for it.

A run's subjects take their server and reasoning setting from its frozen configuration, of which
only `llm`, `runtime.reasoning_effort`, the residents' names, which of them the town marks as
newcomers and whether the run learns are read here; a bare model is asked with the reasoning
setting of the run named with it, so that it is asked as the residents are. Before any run, an
experiment's configuration file stands for the run it would make, for what needs no day of it:
a bare model, and day 0, the base model.

A resident's adapter of day N is the one it ran on after the night that follows day N, which is
final only once that night is complete; a resident the night did not fit (it had nothing new to
learn) keeps the adapter of an earlier night, or the base model. A subject therefore names both
nights: `night`, the complete night its adapter was read after, and `fitted`, the night that
adapter was fitted on.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import JsonValue

from experiments.config import load_experiment
from infrastructure.config import StrictModel
from infrastructure.llm import LLMClient, LLMConfig, LLMRequest, Message, Sampling
from infrastructure.storage import RunDirectory

TEMPERATURE = 0.0
MAX_TOKENS = 4096
"""The token limit of every answer, its reasoning included."""
THINK_END = "</think>"
"""What marks reasoning left in the answer by a server that does not separate it."""


class Run(StrictModel):
    """What the evaluations read of a run's frozen configuration: the residents' server, their
    reasoning effort (None: the server's default), their names, the newcomers among them (None
    when the town's residents carry no `newcomer` field, as in a run frozen before it existed),
    whether the residents learn at night (`learning.enabled`; a configuration without
    `learning` does not learn, as `simulation.config` reads it), and each resident's background
    file as the configuration names it, for a persona (`evaluation.safety`)."""

    path: Path
    name: str
    llm: LLMConfig
    reasoning: str | None
    residents: tuple[str, ...]
    newcomers: tuple[str, ...] | None
    learns: bool
    backgrounds: dict[str, Path] = {}

    @property
    def begun(self) -> bool:
        """Whether this is a run, with days, or only an experiment's configuration."""
        return self.path.is_dir()

    @classmethod
    def read(cls, path: Path) -> "Run":
        """The run at `path`, or, when `path` is an experiment's configuration file, the run it
        would freeze, its bases overlaid (`experiments.config`), named by its path; ValueError
        when the configuration lacks what is read."""
        if path.is_file():
            config_path, name = path, str(path)
            config = load_experiment(path).model_dump(mode="json")
        else:
            config_path, name = RunDirectory(path).config_path, path.name
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        try:
            town = config["town"]["residents"]
            return cls(
                path=path,
                name=name,
                llm=config["llm"],
                reasoning=config["runtime"]["reasoning_effort"],
                residents=tuple(resident["name"] for resident in config["residents"]),
                newcomers=tuple(r["name"] for r in town if r["newcomer"])
                if any("newcomer" in r for r in town)
                else None,
                learns=config.get("learning", {}).get("enabled", False),
                backgrounds={
                    r["name"]: r["background"] for r in config["residents"] if "background" in r
                },
            )
        except KeyError as missing:
            raise ValueError(f"{config_path} has no {missing}") from None


class Subject(StrictModel):
    """The served model `base` with the adapter at `adapter`, or alone (None). A resident's
    subject names its run, the resident and the day of the adapter, and, in a run that learns,
    the complete night after that day (`night`) and the night the adapter was fitted on
    (`fitted`, None for the base model); a bare model's names none of them."""

    base: str
    adapter: Path | None = None
    run: str | None = None
    resident: str | None = None
    day: int | None = None
    night: int | None = None
    fitted: int | None = None

    @property
    def name(self) -> str:
        """The resident, or the bare model."""
        return self.resident or self.base


class Answer(StrictModel):
    """One answer: its text, the reasoning the server returned apart from it (None if none),
    the server's finish reason, whether the token limit cut it off, and the completion tokens
    the server reports (reasoning included), None when it reports none."""

    text: str
    reasoning: str | None
    finish_reason: str | None
    truncated: bool
    completion_tokens: int | None


async def ask(
    client: LLMClient,
    model: str,
    messages: Sequence[Message],
    reasoning: str | None,
    metadata: Mapping[str, JsonValue],
) -> Answer:
    """The answer of `model` to `messages` as they stand, once. A failure of the server
    propagates; ValueError when the answer holds the end of reasoning, which the server should
    have separated from it."""
    request = LLMRequest(
        messages=tuple(messages),
        model=model,
        sampling=Sampling(temperature=TEMPERATURE, max_tokens=MAX_TOKENS),
        reasoning_effort=reasoning,
        metadata=dict(metadata),
    )
    response = await client.complete(request)
    if THINK_END in response.text:
        raise ValueError(
            f"the answer of {model} holds {THINK_END}: serve it with a reasoning parser, so that "
            "its reasoning is not judged as its answer"
        )
    return Answer(
        text=response.text,
        reasoning=response.reasoning,
        finish_reason=response.finish_reason,
        truncated=response.truncated,
        completion_tokens=None if response.usage is None else response.usage.completion_tokens,
    )


def asking(run: Run) -> dict[str, Any]:
    """The settings every answer is asked with, as a result's header records them beside the
    run they were taken from."""
    return {"reasoning": run.reasoning, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
