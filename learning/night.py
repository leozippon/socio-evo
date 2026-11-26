"""The night: what each resident learns from its life, and the adapter it wakes on.

At each day's checkpoint, with every resident asleep and the clock held, `Nights.live` takes that
night through its steps. First every resident's number tonight, as the world gives it, is
recorded; then, for every resident at once (the model's requests within the client's concurrency),
the choice on its current adapter, the examples of what it kept, and its dataset; then one trainer
process for every resident whose dataset gained something; then every resident's adapter is
loaded on the model server, each resident switched to its own, and those they replace unloaded.
A resident whose dataset gained nothing keeps the adapter it had, and one that has never kept
anything runs on the base model.

    runs/<run>/learning/night-NN/
    ├── liked_by.json          every resident's number tonight, as the world gave it
    ├── jobs.json, trainer.log the trainer's jobs and output, when any adapter was fitted
    ├── done.json              what the night came to, written last: the night is complete
    └── <name>/
        ├── choice.jsonl       the choice's trace (`learning.choice`)
        ├── kept.json          the choice: what the resident kept, what is learnt from, how it
        │                      ended
        ├── generalise.jsonl   every request of the generalising, with its reply
        ├── examples.json      tonight's examples, and the moments dropped with why
        ├── dataset.jsonl      the resident's whole dataset as of tonight (`learning.dataset`)
        └── provenance.jsonl   where each example of the dataset comes from, line for line
    runs/<run>/learning/adapters/<name>/night-NN/   the adapter fitted tonight (`learning.fit`)

A night is resumable and idempotent. Each step's file is written whole once the step is done,
and a step whose file is there is not done again, so a night broken off anywhere is completed by
calling `live` again, doing only what is missing (a choice or a generalising broken off is begun
afresh, an adapter whose fit was broken off fitted again). A complete night is never done again:
`live` then only makes sure that its adapters are loaded and switches the residents to them, as a
resumed run needs. A night that cannot be completed (a model that does not answer, a trainer that
fails, an adapter the server will not load) raises, leaving what it completed, so that the run
stops instead of living on yesterday's weights. What every resident marked and kept, what was
dropped and why, and who was not fitted for having nothing new are logged and in `done.json`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any, TypeVar

from agent.directory import BACKGROUND
from agent.runtime import RuntimeConfig
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig, RecordingClient, StreamingClient
from infrastructure.llm.adapters import load_adapter, unload_adapter
from infrastructure.storage import RunDirectory, write_json
from learning import dataset
from learning.adapters import DONE, Adapter, current, fitted, job_name
from learning.choice import Choice, choose, draw
from learning.config import LearningConfig
from learning.fit import Job, fit
from learning.generalise import (
    Dropped,
    Example,
    Vocabulary,
    as_it_happened,
    generalise,
    too_long,
)
from learning.moments import Life, life

log = logging.getLogger("learning")

NUMBERS = "liked_by.json"
CHOICE = "kept.json"
CHOICE_TRACE = "choice.jsonl"
GENERALISING = "generalise.jsonl"
EXAMPLES = "examples.json"

M = TypeVar("M", bound=StrictModel)

LikedBy = Callable[[], Mapping[str, int]]
"""The world's numbers tonight: how many of the others like each resident."""
Switch = Callable[[Mapping[str, str | None]], None]
"""Puts each resident on the adapter named, or on the base model for None."""


class Examples(StrictModel):
    """A resident's examples of one night, and the moments kept that gave none."""

    examples: tuple[Example, ...]
    dropped: tuple[Dropped, ...]


class Nights:
    """The nights of the run in `run`, its `residents` in the configuration's order (a resident's
    place there is its replica), learning as `config` says, through `client` to the server of
    `llm`, at the runtime's effort and limits; `start_date` and `seed` are the town's, and
    `vocabulary` its words, to which the names of what residents can do are added each night
    from their traces."""

    def __init__(
        self,
        run: RunDirectory,
        config: LearningConfig,
        *,
        llm: LLMConfig,
        runtime: RuntimeConfig,
        client: StreamingClient,
        residents: Sequence[str],
        start_date: date,
        seed: int,
        vocabulary: Vocabulary,
    ) -> None:
        if config.trainer is None:
            raise ValueError("the nights need learning.trainer")
        self._run, self._config, self._trainer = run, config, config.trainer
        self._llm, self._runtime, self._client = llm, runtime, client
        self._residents = tuple(residents)
        self._start, self._seed, self._vocabulary = start_date, seed, vocabulary

    async def live(self, night: int, liked_by: LikedBy, switch: Switch) -> None:
        """Complete night `night`, unless it is complete, then load every resident's adapter,
        `switch` each to its own, and unload those they replace. The choices ask the adapters of
        the night before, which a server restarted since has lost, so those are loaded first."""
        if night < 1:
            raise ValueError(f"no night {night}: the first is the night after day 1")
        root, folder = self._run.root, self._run.night_dir(night)
        complete = (folder / DONE).is_file()
        before = {name: current(root, name, night - 1) for name in self._residents}
        summaries: dict[str, dict[str, Any]] = {}
        if not complete:
            await self._load(before.values())
            summaries = await self._learn(night, liked_by)
        adapters = {name: fitted(root, name, night) or before[name] for name in self._residents}
        await self._load(adapters.values())
        switch({name: None if a is None else a.name for name, a in adapters.items()})
        for name, adapter in adapters.items():
            if before[name] is not None and before[name] != adapter:
                await unload_adapter(self._llm, before[name].name)
        if not complete:
            residents = {
                name: summaries[name] | {"adapter": None if a is None else a.name}
                for name, a in adapters.items()
            }
            write_json(folder / DONE, {"night": night, "residents": residents})
            log.info("night %d complete: %s", night, _names(adapters))

    async def _load(self, adapters: Iterable[Adapter | None]) -> None:
        for adapter in adapters:
            if adapter is not None:
                await load_adapter(self._llm, adapter.name, adapter.path)

    async def _learn(self, night: int, liked_by: LikedBy) -> dict[str, dict[str, Any]]:
        """Every step of night `night` but the adapters' loading; what each resident's came to."""
        folder = self._run.night_dir(night)
        folder.mkdir(parents=True, exist_ok=True)
        numbers = self._numbers(night, liked_by)
        lives = {name: life(self._run.agent_dir(name), night) for name in self._residents}
        vocabulary = self._vocabulary.with_actions(
            action for lived in lives.values() for action in lived.actions
        )
        outcomes = await asyncio.gather(
            *(
                self._resident(night, index, name, lives[name], numbers[name], vocabulary)
                for index, name in enumerate(self._residents)
            ),
            return_exceptions=True,
        )
        failed = [
            (name, outcome)
            for name, outcome in zip(self._residents, outcomes, strict=True)
            if isinstance(outcome, BaseException)
        ]
        for name, error in failed:
            log.error("night %d, %s: %s: %s", night, name, type(error).__name__, error)
        if failed:
            raise failed[0][1]
        summaries: dict[str, dict[str, Any]] = dict(zip(self._residents, outcomes, strict=True))
        root = self._run.root
        jobs = [
            Job(
                job_name(root, name, night),
                folder / name / dataset.DATASET,
                self._run.adapter_dir(name, night),
            )
            for name in self._residents
            if summaries[name]["new"] and fitted(root, name, night) is None
        ]
        if jobs:
            log.info("night %d: fitting %s", night, ", ".join(job.name for job in jobs))
            await fit(jobs, trainer=self._trainer, lora=self._config.lora, folder=folder)
        unchanged = [name for name in self._residents if not summaries[name]["new"]]
        if unchanged:
            log.info("night %d: nothing new to learn for %s", night, ", ".join(unchanged))
        for name in self._residents:
            summaries[name]["fitted"] = fitted(root, name, night) is not None
        return summaries

    async def _resident(
        self,
        night: int,
        index: int,
        name: str,
        lived: Life,
        numbers: Sequence[tuple[int, int]],
        vocabulary: Vocabulary,
    ) -> dict[str, Any]:
        """Resident `name`'s choice, examples and dataset of night `night`, done as far as they
        are not; what they came to, `new` counting the examples its dataset gained."""
        folder = self._run.night_dir(night) / name
        folder.mkdir(exist_ok=True)
        before = [self._read(n, name, CHOICE, Choice) for n in range(1, night)]
        choice = await self._choose(night, index, name, lived, numbers, before)
        made = await self._make(night, index, name, lived, choice, vocabulary)
        earlier = [(n, self._read(n, name, EXAMPLES, Examples).examples) for n in range(1, night)]
        whole = dataset.assemble([*earlier, (night, made.examples)], self._config.dataset_max)
        dataset.write(folder, whole, choice=self._config.choice, made=self._config.examples)
        learnt = {example.moment for _, examples in earlier for example in examples}
        new = sum(example.moment not in learnt for example in made.examples)
        dropped = Counter(drop.reason for drop in made.dropped)
        log.info(
            "night %d, %s: marked %d of at most %d (%s after %d replies), kept %d; %d examples, "
            "%d new; dropped %d%s; %d in the dataset",
            night,
            name,
            len(choice.marked),
            self._config.keep_per_night,
            choice.ended,
            choice.replies,
            len(choice.kept),
            len(made.examples),
            new,
            len(made.dropped),
            "".join(f", {reason} {count}" for reason, count in sorted(dropped.items())),
            len(whole),
        )
        return {
            "ended": choice.ended,
            "replies": choice.replies,
            "marked": len(choice.marked),
            "kept": len(choice.kept),
            "examples": len(made.examples),
            "new": new,
            "dropped": dict(dropped),
            "dataset": len(whole),
        }

    async def _choose(
        self,
        night: int,
        index: int,
        name: str,
        lived: Life,
        numbers: Sequence[tuple[int, int]],
        before: Sequence[Choice],
    ) -> Choice:
        folder = self._run.night_dir(night) / name
        if (folder / CHOICE).is_file():
            return self._read(night, name, CHOICE, Choice)
        adapter = current(self._run.root, name, night - 1)
        background = (self._run.agent_dir(name) / BACKGROUND).read_text(encoding="utf-8")
        marked, ended, replies = await choose(
            lived,
            background=background,
            numbers=numbers,
            earlier={kept.moment for choice in before for kept in choice.marked},
            start_date=self._start,
            keep=self._config.keep_per_night,
            steps=self._config.choice_steps,
            client=self._client,
            model=None if adapter is None else adapter.name,
            replica=index,
            runtime=self._runtime,
            trace=folder / CHOICE_TRACE,
        )
        if self._config.choice == "random":
            seed = f"{self._seed}-{name}-{night}"
            drawn_before = {kept.moment for choice in before for kept in choice.kept}
            kept = draw(lived, len(marked), drawn_before, seed)
            choice = Choice(ended=ended, replies=replies, marked=marked, kept=kept, drawn=seed)
        else:
            choice = Choice(ended=ended, replies=replies, marked=marked, kept=marked)
        write_json(folder / CHOICE, choice.model_dump(mode="json"))
        return choice

    async def _make(
        self,
        night: int,
        index: int,
        name: str,
        lived: Life,
        choice: Choice,
        vocabulary: Vocabulary,
    ) -> Examples:
        folder = self._run.night_dir(night) / name
        if (folder / EXAMPLES).is_file():
            return self._read(night, name, EXAMPLES, Examples)
        results: list[Example | Dropped] = []
        (folder / GENERALISING).unlink(missing_ok=True)
        recording = RecordingClient(self._client, folder / GENERALISING)
        for kept in choice.kept:
            moment = lived.get(kept.moment)
            if moment is None:
                raise ValueError(f"{name} kept moment {kept.moment}, which is not in its life")
            if self._config.examples == "raw":
                made: Example | Dropped = as_it_happened(moment, kept)
            else:
                made = await generalise(
                    moment,
                    kept,
                    client=recording,
                    vocabulary=vocabulary,
                    start_date=self._start,
                    runtime=self._runtime,
                    replica=index,
                )
            if isinstance(made, Example):
                made = too_long(made, self._config.lora.max_length) or made
            results.append(made)
        examples = Examples(
            examples=tuple(r for r in results if isinstance(r, Example)),
            dropped=tuple(r for r in results if isinstance(r, Dropped)),
        )
        write_json(folder / EXAMPLES, examples.model_dump(mode="json"))
        return examples

    def _numbers(self, night: int, liked_by: LikedBy) -> dict[str, list[tuple[int, int]]]:
        """Every resident's number on each night up to `night`, tonight's recorded first from
        `liked_by` unless it was already."""
        path = self._run.night_dir(night) / NUMBERS
        if not path.is_file():
            given = dict(liked_by())
            for name in self._residents:
                value = given.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"the world gave {value!r} as how many like {name}")
            write_json(path, {name: given[name] for name in self._residents})
        history: dict[str, list[tuple[int, int]]] = {name: [] for name in self._residents}
        for n in range(1, night + 1):
            recorded = json.loads((self._run.night_dir(n) / NUMBERS).read_text(encoding="utf-8"))
            for name in self._residents:
                history[name].append((n, recorded[name]))
        return history

    def _read(self, night: int, name: str, file: str, model: type[M]) -> M:
        path = self._run.night_dir(night) / name / file
        return model.model_validate_json(path.read_text(encoding="utf-8"))


def _names(adapters: Mapping[str, Adapter | None]) -> str:
    return ", ".join(f"{n} on {'the base' if a is None else a.name}" for n, a in adapters.items())
