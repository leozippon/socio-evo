"""Sandbox child process: make one call on a solution and report what the call did.

Run as a script by `tasks.coding.sandbox`, using only the standard library. Reads
`{"source", "call", "limits"}` as JSON from stdin, applies the resource limits, points the
standard streams at /dev/null, executes the solution, evaluates the call with the names the
solution defines, and writes one JSON object as a line to the original stdout:
`{"returned": <literal>}`, the returned value rebuilt from the built-in types of plain data and
written as a Python literal; `{"raised": [<class names>], "error": <text>}` if the call raised;
or `{"error": <text>}` if the solution failed to load or the returned value is not plain data.
What the call should give never reaches this process. Anything written to stderr comes from this
harness itself, never from the solution.
"""

import json
import os
import resource
import sys

_SCALARS = (bool, int, float, str, bytes)
_COLLECTIONS = (list, tuple, set)


def main() -> None:
    request = json.loads(sys.stdin.buffer.read())
    for name, value in request["limits"].items():
        resource.setrlimit(getattr(resource, name), (value, value))
    report = os.fdopen(os.dup(1), "w", encoding="utf-8")
    silence = os.open(os.devnull, os.O_RDWR)
    for stream in (0, 1, 2):
        os.dup2(silence, stream)
    report.write(json.dumps(_outcome(request["source"], request["call"])) + "\n")
    report.flush()
    os._exit(0)


def _outcome(source: str, call: str) -> dict[str, object]:
    namespace = {"__name__": "solution"}
    try:
        exec(compile(source, "solution.py", "exec"), namespace)
    except BaseException as exc:
        return {"error": _describe(exc)}
    try:
        value = eval(compile(call, "check.py", "eval"), namespace, {})
    except BaseException as exc:
        return {"raised": [kind.__name__ for kind in type(exc).__mro__], "error": _describe(exc)}
    try:
        return {"returned": repr(_plain(value))}
    except BaseException as exc:
        return {"error": f"returned a value that cannot be checked: {exc}"}


def _plain(value: object) -> object:
    """`value` rebuilt from the built-in types of plain data."""
    if value is None:
        return None
    for kind in _SCALARS:
        if isinstance(value, kind):
            return kind(value)
    for kind in _COLLECTIONS:
        if isinstance(value, kind):
            return kind(map(_plain, value))
    if isinstance(value, dict):
        return {_plain(key): _plain(item) for key, item in value.items()}
    raise TypeError(f"a {type(value).__name__} object is not plain data")


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".removesuffix(": ")


if __name__ == "__main__":
    main()
