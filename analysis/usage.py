"""Model usage: aggregates of the model-call logs, never the calls themselves."""

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analysis.run import RunData, read_records
from core.interaction import day_of


@dataclass
class Usage:
    """The model calls of one group. Failed calls count among the calls; the mean latency of
    a group is `latency / (calls - failed)`."""

    calls: int = 0
    """Calls recorded, failed ones included."""
    failed: int = 0
    """Calls that ended in an error, with no reply."""
    retried: int = 0
    """Calls that asked again after an invalid reply (attempt 2 or later)."""
    unmetered: int = 0
    """Answered calls for which the backend reported no token usage, as in dry runs; their
    tokens are missing from the sums."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency: float = 0.0
    """Seconds, summed over the answered calls."""


def run_usage(run: RunData) -> list[dict[str, Any]]:
    """The run's model calls by simulated day, agent and purpose (`act`, `diary`, `reflect`,
    `skills`, `policy`), ordered so. Calls of a day discarded by a resume stay counted: they
    did happen."""
    groups = usage(
        run.directory.llm_calls_path,
        lambda meta: (day_of(meta["time"]), meta["agent"], meta["purpose"]),
    )
    return [
        {"day": day, "agent": agent, "purpose": purpose, **vars(total)}
        for (day, agent, purpose), total in sorted(groups.items())
    ]


def evaluation_usage(run: RunData) -> list[dict[str, Any]]:
    """The model calls of the run's evaluations by purpose (`act` for the evaluated agents,
    `judge` for the judge)."""
    groups = usage(run.directory.evaluation_calls_path, lambda meta: meta["purpose"])
    return [{"purpose": purpose, **vars(total)} for purpose, total in sorted(groups.items())]


def usage(path: Path, key: Callable[[dict[str, Any]], Hashable]) -> dict[Hashable, Usage]:
    """The calls logged in `path`, grouped by `key` of their metadata. Raises ValueError for a
    record that is not a model call."""
    groups: dict[Hashable, Usage] = {}
    for number, record in enumerate(read_records(path), start=1):
        try:
            metadata, response = record["metadata"], record["response"]
            total = groups.setdefault(key(metadata), Usage())
            total.calls += 1
            total.retried += metadata.get("attempt", 1) > 1
            if response is None:
                total.failed += 1
                continue
            total.latency += response["latency"]
            if response["usage"] is None:
                total.unmetered += 1
            else:
                total.prompt_tokens += response["usage"]["prompt_tokens"]
                total.completion_tokens += response["usage"]["completion_tokens"]
        except (KeyError, TypeError) as error:
            raise ValueError(f"{path}:{number}: not a model call record: {error!r}") from error
    return groups
