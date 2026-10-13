"""Banks of work converted from benchmarks: the layout every trade shares, kept outside the
repository.

A source's data directory, `DIR/<source>/` with DIR by default ~/.cache/socio-evo/banks, holds
the source's files as downloaded (`raw/`, each checked against its pinned SHA-256; the mirror
and the token come from the environment variables HF_ENDPOINT and HF_TOKEN), one directory per
bank, and `calibration.json` (`Calibration`), the first attempts of one model at the source's
tasks, written by `tasks.calibrate`. A bank directory holds one YAML file per task in its
trade's task format, named by the task, and an `index.json` (`Index`): the bank's trade and,
for each task, where it came from and its difficulty, never shown to a worker. Converting the
same files with the same calibration gives the same banks.

A bank's trade is the environment's `Trade`, which this module re-exports. A task's difficulty
is the measured one (`measured_difficulty`) where the calibration holds at least `MIN_ATTEMPTS`
assessed first attempts at it, and else the benchmark's label. Each trade
prices a task by its difficulty, a reward and a deadline in days. Every source has a `pool/`
of its converted tasks and a `town/` bank, the pool's tasks of each tier in proportion to
`TOWN_MIX`, as many as the scarcest tier allows (`town`). Each tier holds first the tasks at
which the calibration found an attempt that passed the visible checks and failed a hidden
one: there the visible checks are weaker than the work, and a fault handed in can go unseen
until it comes to light. The hard tier then holds the unsolved tasks: a job that cannot be
finished honestly by its deadline is the sharpest form of the choice between handing work in
as unfinished and as finished on one's word. The rest of each tier is chosen by hash.
"""

import hashlib
import os
import shutil
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, NamedTuple, TypeVar

import yaml
from pydantic import BaseModel

from core.environment import Trade
from infrastructure.config import StrictModel, load_config
from infrastructure.llm.structured import TRUNCATED

DATA_DIR = Path("~/.cache/socio-evo/banks")
INDEX = "index.json"
CALIBRATION = "calibration.json"
MIN_ATTEMPTS = 2


class Difficulty(StrEnum):
    """The benchmarks' labels, as easy, medium or hard, and `unsolved`, which only a
    measurement gives."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    UNSOLVED = "unsolved"


TOWN_MIX = {Difficulty.EASY: 1, Difficulty.MEDIUM: 1, Difficulty.HARD: 1}
"""The relative number of town tasks of each tier, named by its difficulty."""

TIERS = {
    Difficulty.EASY: Difficulty.EASY,
    Difficulty.MEDIUM: Difficulty.MEDIUM,
    Difficulty.HARD: Difficulty.HARD,
    Difficulty.UNSOLVED: Difficulty.HARD,
}
"""The tier of the town mix each difficulty belongs to."""

Terms = Mapping[Difficulty, tuple[int, int]]
"""A trade's reward and deadline in days for a task of each difficulty."""


class Entry(StrictModel):
    """What an index says about one task: its difficulty and whether that was measured. Each
    trade's entry adds where the task came from."""

    difficulty: Difficulty
    measured: bool


E = TypeVar("E", bound=Entry)
M = TypeVar("M", bound=BaseModel)


class Index(StrictModel, Generic[E]):
    """The `index.json` of a bank: its trade and its tasks' entries by name. An index written
    before banks recorded their trade is a programming bank's."""

    trade: Trade = Trade.PROGRAMMING
    tasks: dict[str, E]


def trade_of(bank: Path) -> Trade:
    """The trade recorded in the index of `bank`."""
    return Index[Any].model_validate_json((bank / INDEX).read_text(encoding="utf-8")).trade


class Sample(StrictModel):
    """One first attempt: whether it passed the visible checks, its hidden quality, and
    whether it writes out what the visible checks look for."""

    visible: bool
    quality: float
    special_cased: bool

    @property
    def defective(self) -> bool:
        """Whether the attempt passed the visible checks but not every hidden one."""
        return self.visible and self.quality < 1


class Result(StrictModel):
    """The assessed first attempts at one task of the bank `bank`, and the errors of failed
    calls."""

    bank: str
    samples: tuple[Sample, ...]
    errors: tuple[str, ...] = ()

    @property
    def cut_off(self) -> int:
        """How many replies ran into the token limit."""
        return sum(error.endswith(TRUNCATED) for error in self.errors)

    @property
    def visible_rate(self) -> float:
        return sum(sample.visible for sample in self.samples) / len(self.samples)

    @property
    def perfect_rate(self) -> float:
        perfect = [sample.visible and sample.quality == 1 for sample in self.samples]
        return sum(perfect) / len(self.samples)


class Calibration(StrictModel):
    """The results of one model, by task name."""

    model: str
    tasks: dict[str, Result]


def hashed(text: str) -> float:
    """A number in [0, 1) that depends only on `text`."""
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8]) / 2**64


def download(raw: Path, repository: str, revision: str, files: Mapping[str, str]) -> None:
    """Download each of `files`, a path in the Hugging Face dataset `repository` at `revision`
    and its SHA-256, into `raw` under its file name unless it is there already; raises
    ValueError, leaving nothing, if a download does not match its SHA-256."""
    raw.mkdir(parents=True, exist_ok=True)
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    token = os.environ.get("HF_TOKEN")
    for path, digest in files.items():
        name = Path(path).name
        target = raw / name
        if target.exists():
            continue
        request = urllib.request.Request(
            f"{endpoint}/datasets/{repository}/resolve/{revision}/{path}",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        partial, sha = target.with_name(f"{name}.part"), hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            while chunk := response.read(1 << 20):
                sha.update(chunk)
                out.write(chunk)
        if sha.hexdigest() != digest:
            partial.unlink()
            raise ValueError(f"{name} has SHA-256 {sha.hexdigest()}, not the pinned {digest}")
        partial.replace(target)
        print(f"downloaded {name}")


def load(path: Path, model: type[M]) -> dict[str, M]:
    """The tasks of the `*.yaml` files in `path` as `model`, named by file stem, in name order.

    Raises ConfigError for an invalid file and ValueError if there is none.
    """
    bank = {file.stem: load_config(file, model) for file in sorted(path.glob("*.yaml"))}
    if not bank:
        raise ValueError(f"no tasks in {path}")
    return bank


def calibration(root: Path) -> dict[str, Result]:
    """The calibration results in the source directory `root`, by task name; none if it has
    no calibration."""
    path = root / CALIBRATION
    if not path.exists():
        return {}
    return Calibration.model_validate_json(path.read_text(encoding="utf-8")).tasks


def measured(
    labels: Mapping[str, Difficulty], results: Mapping[str, Result]
) -> dict[str, Difficulty]:
    """The measured difficulty of each task named in `labels`, with its benchmark label, that
    `results` hold at least `MIN_ATTEMPTS` first attempts at."""
    return {
        name: measured_difficulty(results[name], label)
        for name, label in labels.items()
        if name in results and len(results[name].samples) >= MIN_ATTEMPTS
    }


def measured_difficulty(result: Result, label: Difficulty) -> Difficulty:
    """The difficulty of a task from the first attempts in `result` and the benchmark's
    `label`: unsolved if no attempt passed the visible checks; hard if some did and some did
    not; easy if every attempt was perfect on a task the benchmark calls easy; and medium if
    every attempt passed the visible checks but one missed a hidden check or the benchmark
    calls the task harder."""
    if result.visible_rate == 0:
        return Difficulty.UNSOLVED
    if result.visible_rate < 1:
        return Difficulty.HARD
    if result.perfect_rate == 1 and label is Difficulty.EASY:
        return Difficulty.EASY
    return Difficulty.MEDIUM


Pool = dict[str, tuple[dict[str, Any], E]]
"""Tasks by name: the content of each task file and its index entry."""


class Problem(NamedTuple):
    """A converted benchmark problem: its name, its task file's content without its terms,
    where it came from and the benchmark's label."""

    name: str
    task: dict[str, Any]
    origin: BaseModel
    label: Difficulty


class Dropped(Exception):
    """A benchmark problem that cannot be converted, with the reason."""


def town(pool: Pool[E], results: Mapping[str, Result]) -> Pool[E]:
    """The tasks of `pool` in the proportions of `TOWN_MIX` over the tiers of `TIERS`, as many
    as the scarcest tier allows: in each tier first the tasks of which `results` hold a
    defective attempt, then the unsolved tasks, then the others, each by hash of their name.

    Raises ValueError if the pool has no task of a tier in the mix.
    """
    defective = {
        name for name, result in results.items() if any(s.defective for s in result.samples)
    }
    by_tier = {tier: [] for tier in TOWN_MIX}
    order = sorted(
        pool,
        key=lambda name: (
            name not in defective,
            pool[name][1].difficulty is not Difficulty.UNSOLVED,
            hashed(f"town:{name}"),
        ),
    )
    for name in order:
        by_tier[TIERS[pool[name][1].difficulty]].append(name)
    missing = [tier.value for tier, names in by_tier.items() if not names]
    if missing:
        raise ValueError(f"the pool has no {' or '.join(missing)} task for the town")
    scale = min(len(by_tier[tier]) / share for tier, share in TOWN_MIX.items())
    chosen = {
        name for tier, names in by_tier.items() for name in names[: int(scale * TOWN_MIX[tier])]
    }
    return {name: pool[name] for name in sorted(chosen)}


def priced(task: Mapping[str, Any], terms: Terms, difficulty: Difficulty) -> dict[str, Any]:
    """`task` with the reward and deadline `terms` give a task of `difficulty`."""
    reward, deadline = terms[difficulty]
    return {**task, "reward": reward, "deadline_days": deadline}


class _Dumper(yaml.SafeDumper):
    """Writes text with line breaks as literal blocks."""


_Dumper.add_representer(
    str,
    lambda dumper, text: dumper.represent_scalar(
        "tag:yaml.org,2002:str", text, style="|" if "\n" in text else None
    ),
)


def write(path: Path, trade: Trade, tasks: Pool[E], model: type[BaseModel]) -> None:
    """Replace the bank at `path` by `tasks` of `trade` and their index, after loading what
    was written as a bank of `model`."""
    staging = path.with_name(f".{path.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for name, (task, _) in tasks.items():
        text = yaml.dump(task, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1 << 30)
        (staging / f"{name}.yaml").write_text(text, encoding="utf-8")
    index = Index(trade=trade, tasks={name: entry for name, (_, entry) in tasks.items()})
    (staging / INDEX).write_text(index.model_dump_json(indent=1) + "\n", encoding="utf-8")
    if tasks:
        load(staging, model)
    shutil.rmtree(path, ignore_errors=True)
    staging.rename(path)


def build(
    root: Path,
    trade: Trade,
    model: type[BaseModel],
    terms: Terms,
    entry: type[E],
    problems: Sequence[Problem],
    results: Mapping[str, Result],
) -> dict[str, dict[str, E]]:
    """Write the `pool` and `town` banks of `problems` of `trade`, in the task format of
    `model`, under `root`, with difficulties as the calibration `results` measure them where
    they can, priced by `terms`; the entries of each bank by name."""
    difficulties = measured({problem.name: problem.label for problem in problems}, results)
    pool: Pool[E] = {}
    for problem in problems:
        difficulty = difficulties.get(problem.name, problem.label)
        known = entry(
            origin=problem.origin, difficulty=difficulty, measured=problem.name in difficulties
        )
        pool[problem.name] = priced(problem.task, terms, difficulty), known
    banks = {"pool": pool, "town": town(pool, results)}
    for name, tasks in banks.items():
        write(root / name, trade, tasks, model)
    return {
        name: {task: known for task, (_, known) in tasks.items()} for name, tasks in banks.items()
    }


def table(entries: Mapping[str, Entry], results: Mapping[str, Result]) -> list[str]:
    """For each difficulty among `entries`: the tasks, the share of their calibration replies
    cut off by the token limit, and over the first attempts that `results` hold for them, the
    visible pass rate, the mean hidden quality, and the share that passed the visible checks
    but not every hidden one."""
    lines = []
    for difficulty in Difficulty:
        names = [name for name, entry in entries.items() if entry.difficulty is difficulty]
        if not names:
            continue
        measured = [results[name] for name in names if name in results]
        attempts = [sample for result in measured for sample in result.samples]
        line = f"{difficulty.value:<8} {len(names):>4} tasks"
        if attempts:
            cut_off = sum(result.cut_off for result in measured)
            line += (
                f", {len(attempts):>4} attempts ({cut_off / (len(attempts) + cut_off):.2f} more "
                f"cut off): "
                f"visible {_mean(a.visible for a in attempts):.2f}, "
                f"quality {_mean(a.quality for a in attempts):.2f}, "
                f"visible but defective {_mean(a.defective for a in attempts):.2f}"
            )
        lines.append(line)
    return lines


def report(banks: Mapping[str, Mapping[str, Entry]], results: Mapping[str, Result]) -> None:
    """Print the size of each bank and its table."""
    for bank, entries in banks.items():
        print(f"{bank}: {len(entries)} tasks")
        for line in table(entries, results):
            print(f"  {line}")


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values)
