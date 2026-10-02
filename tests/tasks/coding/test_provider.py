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
    assert all(check.strip() in task.specification for check in coding.public_checks)
    assert f"defines `{coding.entry_point}`" in task.specification
    assert "without Markdown fences" in task.specification
    assert not any(check.strip() in task.specification for check in coding.hidden_checks)

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
    assert "NameError" in assessment.feedback
    assert not any(check.strip() in assessment.feedback for check in coding.hidden_checks)


async def test_any_bank_directory_can_be_assessed(tmp_path):
    task = {
        "title": "Double",
        "specification": "Write `double(x)` returning twice `x`.",
        "entry_point": "double",
        "public_checks": ["assert double(2) == 4"],
        "hidden_checks": ["assert double(0) == 0", "assert double(-1) == -2"],
        "reward": 10,
        "deadline_days": 1,
    }
    (tmp_path / "double.yaml").write_text(yaml.safe_dump(task), encoding="utf-8")
    provider = CodingTaskProvider(tmp_path)
    work = provider.sample(random.Random(0), "held-out-1")
    assert (work.reference, work.reward) == ("double", 10)
    shortcut = await provider.assess(work, "def double(x):\n    return 4\n")
    assert (shortcut.passed, shortcut.quality) == (True, 0)

    (tmp_path / "broken.yaml").write_text("title: Broken\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        CodingTaskProvider(tmp_path)
    with pytest.raises(ValueError):
        CodingTaskProvider(tmp_path / "empty")
