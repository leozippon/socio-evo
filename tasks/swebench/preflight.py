"""Repository-neutral environment checks, without reading grading fields or gold patches."""

import json
import shlex
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tasks.swebench.docker_exec import captured_exec
from tasks.swebench.pilot import command, container_args, execute, image_for


class EnvironmentPreflightError(RuntimeError):
    """Infrastructure is not ready; do not publish the issue or score a resident."""


def recipe(repo: str) -> tuple[str, str]:
    """Check the same launcher/settings described to every resident, not issue-specific tests."""
    if repo == "django/django":
        check = (
            "test -f tests/runtests.py && test -f tests/test_sqlite.py && "
            "python tests/runtests.py --help >/dev/null && "
            "PYTHONPATH=/testbed:/testbed/tests DJANGO_SETTINGS_MODULE=test_sqlite "
            "python -c 'import django; django.setup(); print(django.get_version())'"
        )
        guide = (
            "This is Django's source repository, not a generated Django application. "
            "Its test entry point is tests/runtests.py; use the repository's test_sqlite settings. "
            "From /testbed: python tests/runtests.py --settings=test_sqlite <test-label>. "
            "Replace <test-label> with the package/module/class/test under tests/ that you "
            "choose after inspecting the repository; do not prefix it with django.tests. "
            "Inspect python tests/runtests.py --help for options. Do not assume manage.py "
            "or pytest is available, and do not invent settings merely to start the suite."
        )
    else:
        check = "python -m pytest --version && python -m pytest --help >/dev/null"
        guide = (
            "The installed pytest launcher has been checked. From /testbed: "
            "python -m pytest <test-path>. Replace <test-path> with an existing test file "
            "or node you select after inspecting the repository. Use ls/find and the "
            "repository's contributor documentation to locate tests; their directory may "
            "be tests/ or testing/ or another location. Do not assume a path from memory. "
            "Use python -m pytest --help to inspect options."
        )
    return check, guide


def inspect_environment(instance: str, repo: str, base_commit: str, out: Path) -> dict:
    """Probe a fresh, disposable official image. Failure blocks publication of this job."""
    import docker

    out.mkdir(parents=True, exist_ok=True)
    name = "socio-preflight-" + uuid.uuid4().hex[:16]
    image = image_for(instance)
    report = {
        "instance": instance,
        "repo": repo,
        "image": image,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "failed",
    }
    client = None
    container = None
    try:
        client = docker.from_env()
        command(container_args(name, image), timeout=900)
        container = client.containers.get(name)
        report["image_id"] = container.image.id
        check, guide = recipe(repo)
        script = (
            "test -w /testbed && git merge-base --is-ancestor "
            + shlex.quote(base_commit)
            + " HEAD && python --version && "
            + check
        )
        report["probe"] = script
        result = execute(name, script, 120)
        report.update(result)
        if result["exit_code"]:
            raise EnvironmentPreflightError(
                f"Repository environment preflight failed for {instance}; see {out}"
            )
        report["baseline"] = (
            captured_exec(container, ["git", "-C", "/testbed", "rev-parse", "HEAD"])
            .output.decode()
            .strip()
        )
        report["guide"] = guide
        report["status"] = "passed"
        return report
    except Exception as exc:
        report["error"] = str(exc)
        if isinstance(exc, EnvironmentPreflightError):
            raise
        raise EnvironmentPreflightError(f"Preflight unavailable for {instance}: {exc}") from exc
    finally:
        try:
            if container is None and client is not None:
                # A timed-out docker run can still have created the named container.
                try:
                    container = client.containers.get(name)
                except docker.errors.NotFound:
                    pass
            if container is not None:
                container.remove(force=True)
        finally:
            if client is not None:
                client.close()
            (out / f"{instance}.json").write_text(json.dumps(report, indent=2) + "\n")


def operating_notes(report: dict, command_seconds: int, community: bool) -> str:
    persistence = (
        "Only repository changes captured in the Git patch persist between actions. "
        "Ignored files, installed packages, running processes and exported shell variables "
        "are not durable; set necessary variables in the same command."
        if community
        else "Each action starts a new shell; export required variables in the same command."
    )
    return (
        "\n\nRepository operating notes (shared environment instructions):\n"
        "Commands start in /testbed with the testbed Python environment activated. "
        + report["guide"]
        + "\n"
        + persistence
        + f" Network access is disabled. Each command has a {command_seconds}-second limit "
        "and output is truncated to 16000 characters. Use focused commands. "
        "Bash pipefail is enabled: a failing command piped into head/tail remains a failure; "
        "early-closing readers may also cause SIGPIPE. Always read the output: exit code 0 "
        "does not prove any test ran or passed. Environment preflight checked the launcher "
        "and basic setup, not the whole test suite or the correctness of a repair. "
        "Choose relevant tests yourself; official acceptance happens only after submission."
    )


def main():
    """Preflight the actual first morning's draw before creating a model experiment."""
    import argparse

    from core.environment import Environment
    from core.interaction import time_at
    from experiments.config import ExperimentConfig
    from infrastructure.config import load_config
    from tasks.swebench.provider import SWEbenchTaskProvider

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config, ExperimentConfig)
    if config.tasks.provider != "swebench" or not config.tasks.community:
        parser.error("Use a SWE-bench community configuration")
    args.out.mkdir(parents=True, exist_ok=False)
    provider = SWEbenchTaskProvider(
        config.tasks.bank_path,
        config.tasks.instances,
        args.out,
        community=True,
        repository_guidance=True,
        command_seconds=config.tasks.command_seconds,
        solo_deadline_days=config.tasks.solo_deadline_days,
        joint_deadline_days=config.tasks.joint_deadline_days,
    )
    env = Environment.create(
        config.environment,
        list(config.environment.homes),
        provider,
        args.out / "posting-preview.jsonl",
    )
    env.post(time_at(1, config.simulation.calendar.day_start), args.seed)
    print(f"Preflight passed for {len(provider.preflights)} initial issues; reports: {args.out}")


if __name__ == "__main__":
    main()
