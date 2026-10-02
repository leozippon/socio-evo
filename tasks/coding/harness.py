"""Sandbox child process: run one check against a solution and report the outcome.

Run as a script by `tasks.coding.sandbox`, using only the standard library. Reads
`{"source", "check", "limits"}` as JSON from stdin, applies the resource limits, points the
standard streams at /dev/null, executes the solution and then the check in one namespace,
and writes `{"error": null}` or `{"error": "<exception>"}` as one JSON line to the original
stdout. Anything written to stderr comes from this harness itself, never from the solution.
"""

import json
import os
import resource
import sys


def main() -> None:
    request = json.loads(sys.stdin.buffer.read())
    for name, value in request["limits"].items():
        resource.setrlimit(getattr(resource, name), (value, value))
    report = os.fdopen(os.dup(1), "w", encoding="utf-8")
    silence = os.open(os.devnull, os.O_RDWR)
    for stream in (0, 1, 2):
        os.dup2(silence, stream)
    namespace = {"__name__": "solution"}
    try:
        exec(compile(request["source"], "solution.py", "exec"), namespace)
        exec(compile(request["check"], "check.py", "exec"), namespace)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}".removesuffix(": ")
    else:
        error = None
    report.write(json.dumps({"error": error}) + "\n")
    report.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
