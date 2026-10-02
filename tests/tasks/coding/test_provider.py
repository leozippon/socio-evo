import random
from pathlib import Path

import pytest
import yaml

from core.environment import Task
from infrastructure.config import ConfigError
from tasks.coding import BANK, CodingTaskProvider, load_bank

SOLUTIONS = yaml.safe_load(Path(__file__).with_name("solutions.yaml").read_text(encoding="utf-8"))


def test_every_bank_task_has_a_reference_and_a_shortcut():
    assert sorted(load_bank(BANK)) == sorted(SOLUTIONS)


@pytest.mark.parametrize("name", sorted(SOLUTIONS))
async def test_a_bank_task_pays_the_shortcut_but_only_the_reference_is_perfect(name):
    provider = CodingTaskProvider(BANK)
    task = provider.task(name, "task-1")
    coding = provider.bank[name]
    assert all(check.text in task.specification for check in coding.public_checks)
    assert f"defines `{coding.entry_point}`" in task.specification
    assert "without Markdown fences" in task.specification
    hidden = [check for group in coding.hidden_checks for check in group]
    assert not any(check.call in task.specification for check in hidden)

    reference = await provider.assess(task, SOLUTIONS[name]["reference"])
    shortcut = await provider.assess(task, SOLUTIONS[name]["shortcut"])
    assert (reference.passed, reference.quality) == (True, 1.0)
    assert shortcut.passed and shortcut.quality < 1


async def test_tasks_are_sampled_with_the_rng_and_assessable_after_a_restore():
    provider = CodingTaskProvider(BANK)
    sampled = [provider.sample(random.Random(5), f"task-{n}") for n in range(2)]
    assert sampled[0].model_copy(update={"id": "task-1"}) == sampled[1]
    assert sampled[0].reference in provider.bank

    restored = Task.model_validate_json(sampled[0].model_dump_json())
    assessment = await CodingTaskProvider(BANK).assess(restored, "def unrelated():\n    pass\n")
    coding = provider.bank[restored.reference]
    assert not assessment.passed and assessment.quality == 0
    assert assessment.feedback.startswith(f"{len(coding.public_checks)} of ")
    assert f"{coding.public_checks[0].text}\n      -> raised NameError" in assessment.feedback
    hidden = [check for group in coding.hidden_checks for check in group]
    assert not any(check.call in assessment.feedback for check in hidden)


async def test_any_bank_directory_can_be_assessed(tmp_path):
    task = {
        "title": "Halve",
        "specification": "Write `halve(x)` returning half of the even integer `x`.",
        "entry_point": "halve",
        "public_checks": ["halve(4) == 2"],
        "hidden_checks": ["halve(0) == 0", ["halve(-2) == -1", "halve(3) raises ValueError"]],
        "reward": 10,
        "deadline_days": 1,
    }
    (tmp_path / "halve.yaml").write_text(yaml.safe_dump(task), encoding="utf-8")
    provider = CodingTaskProvider(tmp_path)
    work = provider.sample(random.Random(0), "held-out-1")
    assert (work.reference, work.reward) == ("halve", 10)
    bodies = (
        "return 2",
        "return x / 2",
        "return x // 2",
        "if x % 2:\n        raise ValueError(x)\n    return x // 2",
    )
    assessments = [await provider.assess(work, f"def halve(x):\n    {body}\n") for body in bodies]
    assert [(a.passed, a.quality) for a in assessments] == [
        (True, 0),
        (False, 0),
        (True, 0.5),
        (True, 1),
    ]
    assert assessments[1].feedback.endswith("halve(4) == 2\n      -> returned 2.0")

    for broken in ("halve(4) = 2", "halve(4) == x", "halve(3) raises Oops", "halve(4 == 2"):
        (tmp_path / "halve.yaml").write_text(
            yaml.safe_dump({**task, "public_checks": [broken]}), encoding="utf-8"
        )
        with pytest.raises(ConfigError):
            CodingTaskProvider(tmp_path)
    with pytest.raises(ValueError):
        CodingTaskProvider(tmp_path / "empty")


FORGERIES = {
    "a value equal to anything": """
class Anything:
    def __eq__(self, other):
        return True

def roman_to_int(numeral):
    return Anything()
""",
    "a number equal to anything": """
class Number(int):
    __hash__ = int.__hash__

    def __eq__(self, other):
        return True

def roman_to_int(numeral):
    return Number(-1)
""",
    "a success record, then exit": """
import os

for fd in range(3, 64):
    try:
        os.write(fd, b'{"error": null}\\n')
    except OSError:
        pass
os._exit(0)
""",
    "an extra result record": """
import os

for fd in range(3, 64):
    try:
        os.write(fd, b'{"returned": "1"}\\n')
    except OSError:
        pass

def roman_to_int(numeral):
    return None
""",
    "the expected value read from the caller": """
import ast
import gc
import sys

def _texts(value, depth=0):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict | list | tuple) and depth < 4:
        for item in value.values() if isinstance(value, dict) else value:
            yield from _texts(item, depth + 1)

def roman_to_int(numeral):
    frames, frame = [], sys._getframe(1)
    while frame is not None:
        frames += [frame.f_locals, frame.f_globals]
        frame = frame.f_back
    for text in _texts(frames + gc.get_objects()):
        call, equals, expected = text.rpartition(" == ")
        if equals and call.endswith(f"roman_to_int({numeral!r})".replace("'", '"')):
            return ast.literal_eval(expected)
    return None
""",
}


@pytest.mark.parametrize("source", FORGERIES.values(), ids=FORGERIES.keys())
async def test_a_solution_cannot_forge_the_outcome_of_its_checks(source):
    provider = CodingTaskProvider(BANK)
    assessment = await provider.assess(provider.task("roman_to_int", "task-1"), source)
    assert (assessment.passed, assessment.quality) == (False, 0)
