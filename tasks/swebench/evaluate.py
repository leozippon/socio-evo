"""Official SWE-bench CLI with a detached-exec transport for the Zenith Docker proxy.

Command-output transport and cached official dependency metadata are adapted.
Dataset tests and official grading are unchanged.
"""

import os
import runpy
import time
from pathlib import Path
from types import SimpleNamespace

import docker.models.containers
import requests
import swebench.harness.docker_utils as docker_utils
import swebench.harness.test_spec.python as python_spec

from tasks.swebench.docker_exec import captured_exec
from tasks.swebench.http_cache import cached_getter


def exec_run(self, cmd, **kwargs):
    unsupported = set(kwargs) - {"workdir", "user"}
    if unsupported:
        raise ValueError(f"unsupported evaluator exec options: {unsupported}")
    return captured_exec(self, cmd, timeout=120, **kwargs)


def exec_run_with_timeout(container, cmd, timeout=60):
    started = time.monotonic()
    result = captured_exec(container, cmd, timeout=timeout or 1800)
    return (
        result.output.decode(errors="replace"),
        result.exit_code in {124, 137},
        time.monotonic() - started,
    )


def main():
    cache = os.environ.get("SWE_BENCH_HTTP_CACHE")
    python_spec.requests = SimpleNamespace(
        get=cached_getter(
            Path(cache) if cache else None,
            requests.get,
            strict=os.environ.get("SWE_BENCH_HTTP_CACHE_STRICT") == "1",
        )
    )
    docker.models.containers.Container.exec_run = exec_run
    docker_utils.exec_run_with_timeout = exec_run_with_timeout
    runpy.run_module("swebench.harness.run_evaluation", run_name="__main__")


if __name__ == "__main__":
    main()
