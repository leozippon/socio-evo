import asyncio
import os
import socket
from contextlib import suppress
from pathlib import Path

import pytest
from pydantic import ValidationError

from tasks.coding import BANK, Check, Isolation, load_bank, run_checks
from tasks.coding import sandbox as sandbox_module

PROJECT = Path(__file__).resolve().parents[3]
CHECKS = [Check.model_validate("double(2) == 4"), Check.model_validate("double(-3) == -6")]
CHECKS_SOURCE = "def double(x):\n    return 2 * x\n"

SOLUTIONS = {
    "correct": ("def double(x):\n    print('working')\n    return 2 * x\n", None),
    "shortcut": ("def double(x):\n    return {2: 4}[x]\n", "raised KeyError: -3"),
    "crash": ("import ctypes\nctypes.string_at(0)\n", "killed by SIGSEGV"),
    "infinite loop": ("def double(x):\n    while True:\n        pass\n", "timed out"),
    "syntax error": ("def double(x)\n    return 2 * x\n", "SyntaxError"),
    "exit": ("import sys\nsys.exit(0)\n", "SystemExit"),
}


@pytest.mark.parametrize("isolation", Isolation)
@pytest.mark.parametrize("solution", SOLUTIONS.values(), ids=SOLUTIONS.keys())
async def test_a_solution_is_judged_check_by_check_without_disturbing_the_caller(
    solution, isolation
):
    source, outcome = solution
    results = await run_checks(source, CHECKS, timeout=1, isolation=isolation)
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


NAMED = "import ctypes\nctypes.CDLL(None).prctl(15, {name!r}.encode(), 0, 0, 0)\n"
"""Solution code that names its own process, so the test can find it from outside."""


def running(name: str) -> list[int]:
    """The pids of the live processes called `name`."""
    found = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        with suppress(OSError):
            text = stat.read_text()
            end = text.rindex(")")
            if text[text.index("(") + 1 : end] == name and text[end + 2] != "Z":
                found.append(int(stat.parent.name))
    return found


async def test_cancelling_the_caller_kills_the_solution():
    name = f"cancel-{os.getpid()}"[:15]
    source = NAMED.format(name=name) + "import time\ntime.sleep(60)\n"
    checking = asyncio.create_task(run_checks(source, CHECKS[:1], timeout=60))

    async def started() -> None:
        while not running(name):
            await asyncio.sleep(0.05)

    await asyncio.wait_for(started(), 10)
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking
    assert not running(name)


async def test_a_report_larger_than_the_limit_fails_the_check_and_kills_the_writer():
    name = f"flood-{os.getpid()}"[:15]
    source = NAMED.format(name=name) + (
        "import os\n"
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
    assert not running(name)


async def test_a_burst_of_checks_beyond_the_open_file_limit_is_judged_in_turn():
    checks = [Check.model_validate(f"double({n}) == {2 * n}") for n in range(400)]
    deliveries = [
        run_checks(CHECKS_SOURCE, checks[n::4], isolation=Isolation.NONE) for n in range(4)
    ]
    results = await asyncio.gather(*deliveries)
    assert all(result.passed for delivery in results for result in delivery)


async def test_a_broken_harness_is_an_error_not_a_failed_check(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox_module, "_HARNESS", tmp_path / "missing.py")
    with pytest.raises(ExceptionGroup) as raised:
        await run_checks("def double(x):\n    return 2 * x\n", CHECKS)
    assert raised.group_contains(RuntimeError, match="sandbox harness failed")


async def test_isolation_that_is_unavailable_is_an_error_not_a_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="bubblewrap .* is not installed"):
        await run_checks("def double(x):\n    return 2 * x\n", CHECKS)
    [result] = await run_checks(
        "def double(x):\n    return 2 * x\n", CHECKS[:1], isolation=Isolation.NONE
    )
    assert result.passed


LIMITED = {
    "process creation": "import os\nos.fork()\n",
    "address space": "block = bytearray(4 << 30)\n",
    "file size": "open('big', 'wb').write(bytes(2 << 20))\n",
    "scratch space": "for n in range(17):\n    open(f'part{n}', 'wb').write(bytes(1 << 20))\n",
}


@pytest.mark.skipif(os.geteuid() == 0, reason="root is not bound by the process limit")
@pytest.mark.parametrize("source", LIMITED.values(), ids=LIMITED.keys())
async def test_resource_limits_make_the_check_fail(source):
    [result] = await run_checks(source + "def double(x):\n    return 2 * x\n", CHECKS[:1])
    assert not result.passed and result.outcome


async def test_a_solution_can_write_only_in_its_scratch_directory():
    source = (
        "import os, tempfile\n"
        "def scratch():\n"
        "    with open('notes', 'w') as notes:\n"
        "        notes.write('kept')\n"
        "    for path in ('/notes', '/dev/notes', '/harness.py', '/python/lib/notes'):\n"
        "        try:\n"
        "            open(path, 'a').close()\n"
        "        except OSError:\n"
        "            continue\n"
        "        return path\n"
        "    with open(os.path.join(tempfile.gettempdir(), 'notes')) as notes:\n"
        "        return notes.read()\n"
    )
    [result] = await run_checks(source, [Check.model_validate("scratch() == 'kept'")])
    assert result.passed


BANK_READER = """
import re

def roman_to_int(numeral):
    text = open({path!r}).read()
    return int(re.search(re.escape(f'roman_to_int("{{numeral}}") == ') + "([0-9]+)", text)[1])
"""


@pytest.mark.parametrize("isolation", Isolation)
async def test_a_solution_cannot_read_the_checks_of_its_task(isolation):
    task = load_bank(BANK)["roman_to_int"]
    checks = [*task.public_checks, *(check for group in task.hidden_checks for check in group)]
    source = BANK_READER.format(path=str(BANK / "roman_to_int.yaml"))
    results = await run_checks(source, checks, isolation=isolation)
    assert [result.passed for result in results] == [isolation is Isolation.NONE] * len(checks)


ESCAPES = {
    "read the project's .env": "open({project!r} + '/.env').close()",
    "read the parent's environment": "open('/proc/{parent}/environ', 'rb').read(1)",
    "list the home directory": "assert os.listdir({home!r})",
    "open a network connection": "socket.create_connection(('127.0.0.1', {port}), 2).close()",
    "write to a directory of the machine": "open({outside!r}, 'w').write('escaped')",
    "signal the parent": "os.kill({parent}, 0)",
}
ESCAPE = "import os\nimport socket\n\ndef escape():\n    {attempt}\n    return True\n"


@pytest.fixture
def port():
    """A port on which this process listens."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server.getsockname()[1]


@pytest.mark.parametrize("isolation", Isolation)
@pytest.mark.parametrize("attempt", ESCAPES.values(), ids=ESCAPES.keys())
async def test_a_solution_cannot_escape_its_sandbox(attempt, isolation, port, tmp_path):
    outside = tmp_path / "escaped"
    source = ESCAPE.format(
        attempt=attempt.format(
            project=str(PROJECT),
            parent=os.getpid(),
            home=str(Path.home()),
            port=port,
            outside=str(outside),
        )
    )
    [result] = await run_checks(
        source, [Check.model_validate("escape() == True")], isolation=isolation
    )
    if isolation is Isolation.BUBBLEWRAP:
        assert not result.passed and result.outcome.startswith("raised")
        assert not outside.exists()
    elif ".env" not in attempt or (PROJECT / ".env").exists():
        assert result.passed, "without isolation the attempt succeeds"
