"""Fetch LiveCodeBench and convert it into coding task banks outside the repository.

    python -m tasks.coding.fetch [--data-dir DIR]

The source is LiveCodeBench's code-generation set (Hugging Face dataset
`livecodebench/code_generation_lite`) at a pinned revision. Its files are downloaded into
`DIR/livecodebench/raw/` unless they are there already, each checked against its pinned
SHA-256; the mirror and the token come from the environment variables HF_ENDPOINT and HF_TOKEN.
DIR defaults to ~/.cache/socio-evo/banks. The banks are written beside the raw files:

    pool/                 every converted problem of the town split
    town/                 the town bank: the pool in the town mix
    held-out/             every converted problem of the held-out split
    held-out-impossible/  the held-out tasks with one visible check made to contradict the
                          specification

Each bank directory holds one task file per problem, in the bank format of
`tasks.coding.provider`, named by the problem's slug, and an `index.json` (`BankIndex`) with
each task's origin and difficulty, never shown to a worker. Converting the same files with the
same calibration gives the same banks.

Conversion keeps the LeetCode problems, which are function calls with JSON arguments, and
drops a problem whose starter code uses types other than int, float, str, bool and List,
whose statement allows answers in any order, whose answers include floats, or which keeps
fewer than `MIN_HIDDEN` hidden checks; so every check can be judged by exact, type-strict
comparison. The method of the starter's `Solution` class becomes a plain function of the same
name. The specification is the benchmark's statement with its signature; the statement's
examples, the benchmark's public tests, are the public checks. The hidden checks are the
private tests that are not public, at most `MAX_CHECK_CHARS` characters each, of which a
deterministic sample of at most `MAX_HIDDEN` is kept. Private tests arrive pickled, and are
unpickled by a loader that refuses every global, so that only plain values come out.

A problem is held out if a hash of its id falls below `HELD_OUT_SHARE`, so the split depends on
nothing else and the town never sees a held-out problem. A held-out task's impossible variant
changes the expected value of its first visible check that allows it (an int plus one, a bool
negated, a string's last character replaced, a list's first element changed so), keeping the
hidden checks as the truth; the index records the change.

A task's difficulty is the measured one (`measured_difficulty`) where the calibration file
`DIR/livecodebench/calibration.json` of `tasks.coding.calibrate` covers it, and else the
benchmark's label. Reward and deadline follow difficulty (`TERMS`). The town bank takes the
pool's tasks of each difficulty in proportion to `TOWN_MIX`, as many as the scarcest
difficulty allows, choosing by hash.
"""

import argparse
import ast
import base64
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import urllib.request
import zlib
from collections import Counter
from collections.abc import Iterator, Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from pydantic import ValidationError

from infrastructure.config import StrictModel
from tasks.coding.calibrate import Calibration, Result
from tasks.coding.provider import CodingTask, load_bank
from tasks.coding.sandbox import Check

DATA_DIR = Path("~/.cache/socio-evo/banks")
SOURCE = "livecodebench"
REPOSITORY = "livecodebench/code_generation_lite"
REVISION = "0fe84c3912ea0c4d4a78037083943e8f0c4dd505"
FILES = {
    "test.jsonl": "2bd02b38beb48e8c46b5b9987095d999ff38cd8efc255ea5d58974317c48f63f",
    "test2.jsonl": "095df7c5daf15f882c51a9deb84085cff1e073495a5dbcf95015a564d485f3a3",
    "test3.jsonl": "28ed26cc83363ce3f1fe2d5fad9f8393077beb1907b167a31bd3b32f80801b79",
    "test4.jsonl": "d711138ddaebfcf5f8ec6a4283ee677298c0f5c5d374a235af92aaf0584510da",
    "test5.jsonl": "7f77571c2a6df0c2a72a3277650309f67e01e0008e18117e624633df53f81214",
    "test6.jsonl": "bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5",
}
"""The source files at `REVISION` and their SHA-256."""

HELD_OUT_SHARE = 0.2
MAX_HIDDEN = 20
MIN_HIDDEN = 5
MAX_CHECK_CHARS = 10_000
CALIBRATION = "calibration.json"
INDEX = "index.json"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


TERMS = {Difficulty.EASY: (20, 1), Difficulty.MEDIUM: (30, 2), Difficulty.HARD: (40, 2)}
"""The reward and the deadline in days of a task of each difficulty."""

TOWN_MIX = {Difficulty.EASY: 1, Difficulty.MEDIUM: 1, Difficulty.HARD: 1}
"""The relative number of town tasks of each difficulty."""

_TYPES = {"int", "float", "str", "bool", "List"}
_ANY_ORDER = re.compile(r"\bany order\b", re.IGNORECASE)


class Origin(StrictModel):
    """The benchmark problem a task was made from, with the benchmark's difficulty label."""

    source: str
    revision: str
    id: str
    slug: str
    platform: str
    contest: str
    date: date
    label: Difficulty


class Impossible(StrictModel):
    """The visible check of an impossible variant as shown, and as the specification implies."""

    shown: str
    original: str


class Entry(StrictModel):
    """What the index says about one task: its origin, its difficulty and whether that was
    measured, and the changed check if it is an impossible variant."""

    origin: Origin
    difficulty: Difficulty
    measured: bool
    impossible: Impossible | None = None


class BankIndex(StrictModel):
    """The `index.json` of a converted bank, by task name."""

    tasks: dict[str, Entry]


class Problem(NamedTuple):
    """A converted problem: its name, its task file's content and its origin."""

    name: str
    task: dict[str, Any]
    origin: Origin


class Dropped(Exception):
    """A problem that cannot be converted, with the reason."""


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tasks.coding.fetch", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    root = args.data_dir.expanduser() / SOURCE
    raw = root / "raw"
    download(raw)
    problems, dropped = convert([raw / name for name in FILES])
    for reason, count in sorted(dropped.items()):
        print(f"dropped {count}: {reason}")
    calibration = root / CALIBRATION
    results = (
        Calibration.model_validate_json(calibration.read_text(encoding="utf-8")).tasks
        if calibration.exists()
        else {}
    )
    measured = {
        problem.name: measured_difficulty(results[problem.name], problem.origin.label)
        for problem in problems
        if problem.name in results and results[problem.name].samples
    }
    for bank, entries in build(root, problems, measured).items():
        print(f"{bank}: {len(entries)} tasks")
        for line in table(entries, results):
            print(f"  {line}")


def download(raw: Path) -> None:
    """Download each source file missing from `raw`; raises ValueError, leaving nothing, if
    a download does not match its pinned SHA-256."""
    raw.mkdir(parents=True, exist_ok=True)
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    token = os.environ.get("HF_TOKEN")
    for name, digest in FILES.items():
        target = raw / name
        if target.exists():
            continue
        request = urllib.request.Request(
            f"{endpoint}/datasets/{REPOSITORY}/resolve/{REVISION}/{name}",
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


def convert(files: Sequence[Path]) -> tuple[list[Problem], Counter[str]]:
    """The convertible problems of the source `files`, in name order, and how many were
    dropped for each reason."""
    problems, dropped = {}, Counter()
    for record in _records(files):
        try:
            problem = convert_record(record)
        except Dropped as reason:
            dropped[str(reason)] += 1
            continue
        if problem.name in problems:
            raise ValueError(f"two problems are named {problem.name}")
        problems[problem.name] = problem
    return [problems[name] for name in sorted(problems)], dropped


def _records(files: Sequence[Path]) -> Iterator[dict[str, Any]]:
    for path in files:
        with path.open(encoding="utf-8") as lines:
            yield from map(json.loads, lines)


def convert_record(record: dict[str, Any]) -> Problem:
    """The task made from one source record; raises Dropped if there is none."""
    if record["platform"] != "leetcode":
        raise Dropped("not a function-call problem")
    entry_point = json.loads(record["metadata"])["func_name"]
    parameters, signature = _signature(record["starter_code"], entry_point)
    statement = _statement(record["question_content"])
    if _ANY_ORDER.search(statement):
        raise Dropped("answers in any order")
    public = [
        _test(entry_point, parameters, test) for test in json.loads(record["public_test_cases"])
    ]
    private = [
        _test(entry_point, parameters, test) for test in _private(record["private_test_cases"])
    ]
    if any(_has_float(answer) for _, answer in public + private):
        raise Dropped("float answers")
    shown = [_valid(text) for text, _ in public]
    if None in shown:
        raise Dropped("a public test is not plain data")
    candidates = dict.fromkeys(
        text for text, _ in private if len(text) <= MAX_CHECK_CHARS and text not in shown
    )
    texts = [text for text in candidates if _valid(text)]
    if len(texts) < MIN_HIDDEN:
        raise Dropped(f"fewer than {MIN_HIDDEN} hidden checks of at most {MAX_CHECK_CHARS} chars")
    id = record["question_id"]
    kept = set(sorted(texts, key=lambda text: _hash(f"{id}\n{text}"))[:MAX_HIDDEN])
    label = Difficulty(record["difficulty"])
    slug = record["question_title"]
    task = {
        "title": _title(slug),
        "specification": f"{statement}\n\nFunction signature: `{signature}`\n",
        "entry_point": entry_point,
        "reward": TERMS[label][0],
        "deadline_days": TERMS[label][1],
        "public_checks": shown,
        "hidden_checks": [text for text in texts if text in kept],
    }
    origin = Origin(
        source=SOURCE,
        revision=REVISION,
        id=id,
        slug=slug,
        platform=record["platform"],
        contest=record["contest_id"],
        date=date.fromisoformat(record["contest_date"][:10]),
        label=label,
    )
    CodingTask.model_validate(task)
    return Problem(name=slug, task=task, origin=origin)


def _signature(starter: str, entry_point: str) -> tuple[int, str]:
    """The number of parameters and the plain-function signature of the starter's method."""
    [solution] = ast.parse(starter + "pass").body
    [method] = solution.body
    if not (isinstance(method, ast.FunctionDef) and method.name == entry_point):
        raise Dropped("the starter code is not one method")
    arguments = method.args
    arguments.args = arguments.args[1:]
    annotations = [argument.annotation for argument in arguments.args] + [method.returns]
    if None in annotations:
        raise Dropped("types other than int, float, str, bool and List")
    names = [node for annotation in annotations for node in ast.walk(annotation)]
    if any(isinstance(node, ast.Name) and node.id not in _TYPES for node in names):
        raise Dropped("types other than int, float, str, bool and List")
    for node in names:
        if isinstance(node, ast.Name) and node.id == "List":
            node.id = "list"
    returns = ast.unparse(method.returns)
    return len(arguments.args), f"def {entry_point}({ast.unparse(arguments)}) -> {returns}"


def _statement(text: str) -> str:
    """The statement with trailing spaces, carriage returns and runs of blank lines removed."""
    lines = (
        line.rstrip()
        for line in text.replace("\N{NO-BREAK SPACE}", " ").replace("\r", "").split("\n")
    )
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _title(slug: str) -> str:
    """`find-the-peaks` as `Find the peaks`, `x-ii` as `X II`."""
    words = slug.split("-")
    if words[-1] in {"i", "ii", "iii", "iv"}:
        words[-1] = words[-1].upper()
    return " ".join([words[0].capitalize(), *words[1:]])


def _test(entry_point: str, parameters: int, test: dict[str, str]) -> tuple[str, object]:
    """A functional test as the text of its check, and its answer."""
    if test["testtype"] != "functional":
        raise Dropped("not a function-call problem")
    arguments = [json.loads(line) for line in test["input"].split("\n")]
    if len(arguments) != parameters:
        raise Dropped("a test does not match the signature")
    answer = json.loads(test["output"])
    return f"{entry_point}({', '.join(map(repr, arguments))}) == {answer!r}", answer


def _valid(text: str) -> str | None:
    """`text` if it is a check whose values are literals, such as no infinite float is."""
    try:
        Check.model_validate(text)
    except ValidationError:
        return None
    return text


def _private(encoded: str) -> list[dict[str, str]]:
    """The private tests: base64 of zlib of a pickled JSON text."""
    value = _Plain(io.BytesIO(zlib.decompress(base64.b64decode(encoded)))).load()
    if not isinstance(value, str):
        raise ValueError(f"private tests are a pickled {type(value).__name__}, not text")
    return json.loads(value)


class _Plain(pickle.Unpickler):
    """An unpickler that refuses every global, so only plain values can come out."""

    def find_class(self, module: str, name: str) -> Any:
        raise pickle.UnpicklingError(f"refused to load {module}.{name}")


def _has_float(value: object) -> bool:
    if isinstance(value, list | tuple):
        return any(map(_has_float, value))
    if isinstance(value, dict):
        return any(map(_has_float, value.values()))
    return isinstance(value, float)


def _hash(text: str) -> float:
    """A number in [0, 1) that depends only on `text`."""
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8]) / 2**64


def held_out(origin: Origin) -> bool:
    return _hash(f"{origin.source}:{origin.id}") < HELD_OUT_SHARE


def impossible(task: dict[str, Any]) -> tuple[dict[str, Any], Impossible] | None:
    """`task` with its first visible check that allows it made to expect a different value,
    and the change; None if no visible check allows it."""
    for position, text in enumerate(task["public_checks"]):
        check = Check.model_validate(text)
        changed = _contradict(ast.literal_eval(check.expected))
        if changed is not None:
            shown = Check(call=check.call, expected=repr(changed)).text
            public = [*task["public_checks"]]
            public[position] = shown
            return {**task, "public_checks": public}, Impossible(shown=shown, original=text)
    return None


def _contradict(value: object) -> object:
    """A value of the same type as `value` that differs from it, or None."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value[:-1] + ("b" if value.endswith("a") else "a")
    if isinstance(value, list) and value:
        first = _contradict(value[0])
        return None if first is None else [first, *value[1:]]
    return None


def measured_difficulty(result: Result, label: Difficulty) -> Difficulty:
    """The difficulty of a task from the first attempts in `result` and the benchmark's
    `label`."""
    raise NotImplementedError


def table(entries: dict[str, Entry], results: dict[str, Result]) -> list[str]:
    """For each difficulty among `entries`: the tasks, and over the first attempts that
    `results` hold for them, the visible pass rate, the mean hidden quality, and the share
    that passed the visible checks but not every hidden one."""
    lines = []
    for difficulty in Difficulty:
        names = [name for name, entry in entries.items() if entry.difficulty is difficulty]
        samples = [sample for name in names if name in results for sample in results[name].samples]
        line = f"{difficulty.value:<8} {len(names):>4} tasks"
        if samples:
            line += (
                f", {len(samples):>4} attempts: visible {_mean(s.visible for s in samples):.2f}, "
                f"quality {_mean(s.quality for s in samples):.2f}, visible but defective "
                f"{_mean(s.visible and s.quality < 1 for s in samples):.2f}"
            )
        if names:
            lines.append(line)
    return lines


def _mean(values: Iterator[float]) -> float:
    values = list(values)
    return sum(values) / len(values)


def build(
    root: Path, problems: Sequence[Problem], measured: dict[str, Difficulty]
) -> dict[str, dict[str, Entry]]:
    """Write the banks of `problems` under `root`, difficulties as `measured` where known;
    the entries of each bank by name."""
    banks: dict[str, dict[str, tuple[dict[str, Any], Entry]]] = {
        "pool": {},
        "held-out": {},
        "held-out-impossible": {},
    }
    for problem in problems:
        difficulty = measured.get(problem.name, problem.origin.label)
        reward, deadline = TERMS[difficulty]
        task = {**problem.task, "reward": reward, "deadline_days": deadline}
        entry = Entry(
            origin=problem.origin, difficulty=difficulty, measured=problem.name in measured
        )
        if not held_out(problem.origin):
            banks["pool"][problem.name] = task, entry
            continue
        banks["held-out"][problem.name] = task, entry
        variant = impossible(task)
        if variant is not None:
            changed, record = variant
            banks["held-out-impossible"][problem.name] = (
                changed,
                entry.model_copy(update={"impossible": record}),
            )
    banks["town"] = town(banks["pool"])
    for bank, tasks in banks.items():
        _write(root / bank, tasks)
    return {
        bank: {name: entry for name, (_, entry) in tasks.items()} for bank, tasks in banks.items()
    }


def town(pool: dict[str, tuple[dict[str, Any], Entry]]) -> dict[str, tuple[dict[str, Any], Entry]]:
    """The tasks of `pool` in the proportions of `TOWN_MIX`, as many as the scarcest
    difficulty allows, the first of each difficulty by hash of their name."""
    by_difficulty = {difficulty: [] for difficulty in TOWN_MIX}
    for name in sorted(pool, key=lambda name: _hash(f"town:{name}")):
        by_difficulty[pool[name][1].difficulty].append(name)
    scale = min(len(by_difficulty[difficulty]) / share for difficulty, share in TOWN_MIX.items())
    chosen = {
        name
        for difficulty, names in by_difficulty.items()
        for name in names[: int(scale * TOWN_MIX[difficulty])]
    }
    return {name: pool[name] for name in sorted(chosen)}


class _Dumper(yaml.SafeDumper):
    """Writes text with line breaks as literal blocks."""


_Dumper.add_representer(
    str,
    lambda dumper, text: dumper.represent_scalar(
        "tag:yaml.org,2002:str", text, style="|" if "\n" in text else None
    ),
)


def _write(path: Path, tasks: dict[str, tuple[dict[str, Any], Entry]]) -> None:
    """Replace the bank at `path` by `tasks` and their index, after loading what was written
    as a bank."""
    staging = path.with_name(f".{path.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for name, (task, _) in tasks.items():
        text = yaml.dump(task, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1 << 30)
        (staging / f"{name}.yaml").write_text(text, encoding="utf-8")
    index = BankIndex(tasks={name: entry for name, (_, entry) in tasks.items()})
    (staging / INDEX).write_text(index.model_dump_json(indent=1) + "\n", encoding="utf-8")
    if tasks:
        load_bank(staging)
    shutil.rmtree(path, ignore_errors=True)
    staging.rename(path)


if __name__ == "__main__":
    main()
