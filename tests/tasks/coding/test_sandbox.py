import asyncio
import os

import pytest
from pydantic import ValidationError

from tasks.coding import Check, run_checks
from tasks.coding import sandbox as sandbox_module

CHECKS = [Check.model_validate("double(2) == 4"), Check.model_validate("double(-3) == -6")]

SOLUTIONS = {
    "correct": ("def double(x):\n    print('working')\n    return 2 * x\n", None),
    "shortcut": ("def double(x):\n    return {2: 4}[x]\n", "raised KeyError: -3"),
    "crash": ("import ctypes\nctypes.string_at(0)\n", "killed by SIGSEGV"),
    "infinite loop": ("def double(x):\n    while True:\n        pass\n", "timed out"),
    "syntax error": ("def double(x)\n    return 2 * x\n", "SyntaxError"),
    "exit": ("import sys\nsys.exit(0)\n", "SystemExit"),
}


@pytest.mark.parametrize("solution", SOLUTIONS.values(), ids=SOLUTIONS.keys())
async def test_a_solution_is_judged_check_by_check_without_disturbing_the_caller(solution):
    source, outcome = solution
    results = await run_checks(source, CHECKS, timeout=1)
    assert [result.check for result in results] == CHECKS
    if outcome is None:
        assert [(result.passed, result.outcome) for result in results] == [
            (True, "returned 4"),
            (True, "returned -6"),
        ]
    elif outcome.startswith("raised"):
        assert [result.passed for result in results] == [True, False]
        assert results[1].outcome == outcome
    else:
        assert not any(result.passed for result in results)
        assert all(outcome in result.outcome for result in results)


COMPARED = {
    "same(1) == 1": True,
    "same(1.0) == 1": False,
    "same(True) == 1": False,
    "same(1) == True": False,
    "same([1, 2]) == (1, 2)": False,
    "same(Pair(1, 2)) == (1, 2)": True,
    "same(OrderedDict(b=[2], a=[1])) == {'a': [1], 'b': [2]}": True,
    "same({1: 'a'}) == {True: 'a'}": False,
    "same({3, 1, 2}) == {1, 2, 3}": True,
    "same('x') == b'x'": False,
    "same(iter([1])) == [1]": False,
    "fail('no') raises ValueError": True,
    "fail('no') raises KeyError": False,
    "same(1) raises ValueError": False,
    "fail('no') == None": False,
}
COMPARING = """\
from collections import OrderedDict, namedtuple

Pair = namedtuple("Pair", "a b")

class Refusal(ValueError):
    pass

def same(value):
    return value

def fail(reason):
    raise Refusal(reason)
"""


async def test_a_call_must_return_the_same_plain_data_with_the_same_types_or_raise():
    checks = [Check.model_validate(text) for text in COMPARED]
    results = await run_checks(COMPARING, checks)
    assert {result.check.text: result.passed for result in results} == COMPARED
    outcomes = {result.check.text: result.outcome for result in results}
    assert outcomes["same(1.0) == 1"] == "returned 1.0"
    assert outcomes["same(Pair(1, 2)) == (1, 2)"] == "returned (1, 2)"
    assert outcomes["fail('no') == None"] == "raised Refusal: no"
    assert "list_iterator object is not plain data" in outcomes["same(iter([1])) == [1]"]


def test_a_check_is_a_call_with_a_literal_or_a_built_in_exception():
    check = Check.model_validate(' f("a raises b", [1]) == {"k": (1, 2)} ')
    assert (check.call, check.expected, check.raises) == (
        'f("a raises b", [1])',
        '{"k": (1, 2)}',
        None,
    )
    assert Check.model_validate(check.text) == check
    raising = Check.model_validate('f("") raises ValueError')
    assert (raising.call, raising.raises) == ('f("")', "ValueError")
    assert raising.text == 'f("") raises ValueError'
    for text in [
        "assert f(1) == 2",
        "f(1) == g(2)",
        "f(1) == 2 == 2",
        "f(1) raises Unknown",
        "f(1",
    ]:
        with pytest.raises(ValidationError):
            Check.model_validate(text)


async def test_cancelling_the_caller_kills_the_solution(tmp_path):
    pid_file = tmp_path / "pid"
    source = f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
    checking = asyncio.create_task(run_checks(source + "time.sleep(60)\n", CHECKS[:1], timeout=60))

    async def started() -> None:
        while not (pid_file.exists() and pid_file.read_text()):
            await asyncio.sleep(0.05)

    await asyncio.wait_for(started(), 10)
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


async def test_a_report_larger_than_the_limit_fails_the_check_and_kills_the_writer(tmp_path):
    pid_file = tmp_path / "pid"
    source = (
        f"import os\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "for fd in range(3, 64):\n"
        "    try:\n"
        "        for _ in range(4096):\n"
        "            os.write(fd, bytes(1 << 16))\n"
        "    except OSError:\n"
        "        pass\n"
        "def double(x):\n    return 2 * x\n"
    )
    [result] = await run_checks(source, CHECKS[:1], timeout=30)
    assert not result.passed and result.outcome.startswith("the result was larger than")
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


async def test_a_broken_harness_is_an_error_not_a_failed_check(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox_module, "_HARNESS", tmp_path / "missing.py")
    with pytest.raises(ExceptionGroup) as raised:
        await run_checks("def double(x):\n    return 2 * x\n", CHECKS)
    assert raised.group_contains(RuntimeError, match="sandbox harness failed")


LIMITED = {
    "process creation": "import os\nos.fork()\n",
    "address space": "block = bytearray(4 << 30)\n",
    "file size": "open('big', 'wb').write(bytes(2 << 20))\n",
}


@pytest.mark.skipif(os.geteuid() == 0, reason="root is not bound by the process limit")
@pytest.mark.parametrize("source", LIMITED.values(), ids=LIMITED.keys())
async def test_resource_limits_make_the_check_fail(source):
    [result] = await run_checks(source + "def double(x):\n    return 2 * x\n", CHECKS[:1])
    assert not result.passed and result.outcome
