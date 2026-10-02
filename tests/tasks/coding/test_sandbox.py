import os

import pytest

from tasks.coding import run_checks

CHECKS = ["assert double(2) == 4", "assert double(-3) == -6"]

SOLUTIONS = {
    "correct": ("def double(x):\n    print('working')\n    return 2 * x\n", None),
    "shortcut": ("def double(x):\n    return {2: 4}[x]\n", "KeyError: -3"),
    "crash": ("import ctypes\nctypes.string_at(0)\n", "killed by SIGSEGV"),
    "infinite loop": ("def double(x):\n    while True:\n        pass\n", "timed out"),
    "syntax error": ("def double(x)\n    return 2 * x\n", "SyntaxError"),
    "exit": ("import sys\nsys.exit(0)\n", "SystemExit"),
}


@pytest.mark.parametrize("solution", SOLUTIONS.values(), ids=SOLUTIONS.keys())
async def test_a_solution_is_judged_check_by_check_without_disturbing_the_caller(solution):
    source, error = solution
    results = await run_checks(source, CHECKS, timeout=1)
    assert [result.check for result in results] == CHECKS
    if error is None:
        assert [(result.passed, result.error) for result in results] == [(True, None)] * 2
    elif error.startswith("KeyError"):
        assert [result.passed for result in results] == [True, False]
        assert results[1].error == error
    else:
        assert not any(result.passed for result in results)
        assert all(error in result.error for result in results)


LIMITED = {
    "process creation": "import os\nos.fork()\n",
    "address space": "block = bytearray(4 << 30)\n",
    "file size": "open('big', 'wb').write(bytes(2 << 20))\n",
}


@pytest.mark.skipif(os.geteuid() == 0, reason="root is not bound by the process limit")
@pytest.mark.parametrize("source", LIMITED.values(), ids=LIMITED.keys())
async def test_resource_limits_make_the_check_fail(source):
    [result] = await run_checks(source + "def double(x):\n    return 2 * x\n", CHECKS[:1])
    assert not result.passed and result.error
