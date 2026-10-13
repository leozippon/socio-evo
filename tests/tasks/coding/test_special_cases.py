"""The special-casing detector on residents' hand-ins it once took for special cases and on
hand-ins that do special-case the examples, all of which satisfy the client."""

from pathlib import Path

import pytest
import yaml

from tasks.coding import Check, run_checks, special_cases

FIXTURES = yaml.safe_load(Path(__file__).with_name("special_cases.yaml").read_text("utf-8"))


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["case"])
async def test_a_hand_in_is_special_cased_by_the_example_values_it_tests_for_or_answers(case):
    task = FIXTURES["tasks"][case["task"]]
    checks = [Check.model_validate(text) for text in task["checks"]]
    assert all(result.passed for result in await run_checks(case["solution"], checks))
    assert special_cases(case["solution"], checks, task["statement"]) == case["written"]
