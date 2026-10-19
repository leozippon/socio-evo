"""Repository-neutral environment checks, without reading grading fields or gold patches."""

import json
import shlex
import uuid
from datetime import UTC, datetime
from pathlib import Path

from core.environment.rejection import TaskUnavailable
from tasks.swebench.docker_exec import captured_exec
from tasks.swebench.pilot import command, container_args, execute, image_for


class EnvironmentPreflightError(TaskUnavailable):
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
            "For Django, run python tests/runtests.py --settings=test_sqlite <test-label>. "
            "Labels are relative to tests/: tests/backends/base/test_operations.py uses "
            "backends.base.test_operations; tests/admin_checks/tests.py uses admin_checks. "
            "The repository's contributor documentation and launcher --help describe options."
        )
    else:
        check = "python -m pytest --version && python -m pytest --help >/dev/null"
        guide = (
            "Run python -m pytest <test-path>, using a test file or node from the repository. "
            "Contributor documentation and python -m pytest --help describe test options."
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
        "Repository changes captured in the Git patch persist between commands. "
        "Ignored files, installed packages, processes and shell variables are temporary."
        if community
        else "Files persist between commands; each command starts a new shell."
    )
    verification = (
        "The launcher and basic setup passed environment preflight."
        if report.get("status") == "passed"
        else "Environment preflight has not been performed."
    )
    return (
        "\n\nRepository operating notes:\n"
        "Commands start in /testbed with the testbed Python environment activated. "
        + report["guide"]
        + "\n"
        + persistence
        + f" Network access is disabled. Commands use Bash with pipefail, have a "
        f"{command_seconds}-second limit, and return at most 16000 output characters. "
        + verification
        + " Local test results are shown in the test runner's report; "
        "client acceptance is reported after submission."
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
        strict_http_cache=config.tasks.strict_http_cache,
        evaluation_preflight=config.tasks.evaluation_preflight,
        http_cache=config.tasks.http_cache_path,
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


def inspect_evaluation_environment(row: dict, cache: Path, out: Path) -> dict:
    """Require offline official spec generation and its exact local instance image."""
    from tasks.swebench.environment_spec import inspect_spec

    report = {"instance": row["instance_id"], "status": "failed"}
    client = None
    out.mkdir(parents=True, exist_ok=True)
    try:
        import docker

        report.update(inspect_spec(row, cache))
        report["status"] = "failed"  # Spec generation alone is not complete readiness.
        client = docker.from_env()
        image = client.images.get(report["image"])  # Never pull/build over the network here.
        report["image_id"] = image.id
        report["status"] = "passed"
        return report
    except Exception as error:
        report["error"] = str(error)
        raise EnvironmentPreflightError(
            f"Official evaluation environment not ready for {row['instance_id']}: {error}"
        ) from error
    finally:
        if client is not None:
            client.close()
        (out / f"{row['instance_id']}-evaluation.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
