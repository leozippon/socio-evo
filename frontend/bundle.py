"""The JSON documents of the data bundle, built from a run as `analysis` reads it.

Every document is a plain JSON value; `frontend/README.md` is its contract. Agent files are
read through git plumbing (`log`, `ls-tree`, `cat-file`, `diff`), which never touches an
index or a work tree.
"""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from analysis import Measures, RunData, Score, SocietyDay
from core.agent.evolution import History, Version
from core.interaction import day_of, time_at
from evaluation.results import AgentResult
from infrastructure.git import FileChange, GitError, Repository

POLICY = "parameters/policy.md"
INSIGHTS = "memory/insights.jsonl"
EPISODIC = "memory/episodic.jsonl"
SKILL = re.compile(r"memory/skills/([^/]+)\.md")
DIARY = re.compile(r"memory/diary/day-(\d+)\.md")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def world(run: RunData) -> dict[str, Any]:
    """The town and the rules of the run, from its frozen configuration."""
    config = run.config
    environment, simulation, llm = config["environment"], config["simulation"], config["llm"]
    calendar = simulation["calendar"]
    homes = {agent: place["id"] for place in environment["places"] for agent in place["residents"]}
    return {
        "experiment": config["name"],
        "days": simulation["days"],
        "calendar": calendar,
        "scenes": simulation["scenes"],
        "places": environment["places"],
        "agents": [
            {**seed["profile"], "home": homes[seed["profile"]["name"]], "policy": seed["policy"]}
            for seed in config["agents"]
        ],
        "initial_balance": environment["initial_balance"],
        "conditions": environment["conditions"],
        "esteem_half_life_days": environment["esteem_half_life_days"],
        "task_shelf_life_days": environment["task_shelf_life_days"],
        "interventions": [
            {
                "day": intervention["day"],
                "time": time_at(intervention["day"], intervention["at"] or calendar["day_start"]),
                "conditions": intervention["conditions"],
                "announcement": intervention["announcement"],
            }
            for intervention in simulation["interventions"]
        ],
        "evolution": config["evolution"],
        "model": {"backend": llm["backend"], "name": llm["model"], "sampling": llm["sampling"]},
    }


def event_days(run: RunData) -> dict[int, list[dict[str, Any]]]:
    """Every event of the run, as recorded, by day."""
    days: dict[int, list[dict[str, Any]]] = {}
    for event in run.events:
        days.setdefault(day_of(event.time), []).append(event.model_dump(mode="json"))
    return days


def measures(found: Measures, usage: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "agents": [asdict(row) for row in found.agents],
        "society": [asdict(row) for row in found.society],
        "graph": [asdict(row) for row in found.graph],
        "usage": usage,
    }


def headline(
    society: list[SocietyDay],
    usage: list[dict[str, Any]],
    found: dict[str, AgentResult],
) -> dict[str, Any]:
    """A few numbers for the landing page; see the README for their definitions."""
    delivered = sum(day.delivered for day in society)
    defective = sum(day.defective for day in society)
    esteems = [day.esteem_mean for day in society if day.esteem_mean is not None]
    return {
        "deliveries": delivered,
        "defect_rate": defective / delivered if delivered else None,
        "defects_discovered": sum(day.defects_discovered for day in society),
        "utterances": sum(day.utterances for day in society),
        "balance_mean": society[-1].balance_mean if society else None,
        "esteem_mean": esteems[-1] if esteems else None,
        "evolution_steps": sum(sum(day.evolution.values()) for day in society),
        "model_calls": sum(row["calls"] for row in usage),
        "tokens": sum(row["prompt_tokens"] + row["completion_tokens"] for row in usage),
        "evaluated_days": sorted({result.day for result in found.values()}),
    }


def evaluation(
    rows: list[Score],
    urls: dict[str, str],
    found: dict[str, AgentResult],
    usage: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scores": [asdict(row) for row in rows],
        "results": [
            {
                "label": name.split("/")[0],
                "agent": result.agent,
                "day": result.day,
                "url": urls[name],
            }
            for name, result in found.items()
        ],
        "usage": usage,
    }


@dataclass(frozen=True)
class AgentVersion:
    """A commit of an agent's repository with the files it changed; `parent` is None for
    the first."""

    version: Version
    parent: str | None
    changes: tuple[FileChange, ...]

    @property
    def day(self) -> int:
        return day_of(self.version.time)


def agent_versions(run: RunData, agent: str) -> list[AgentVersion]:
    """The agent's versions, oldest first. Before the run's first checkpoint the agent may not
    have a repository or a commit yet, and then has no versions."""
    repository = Repository(run.directory.agent_dir(agent))
    try:
        log = History(repository.path).log()
    except (GitError, FileNotFoundError):
        if run.checkpoint is None:
            return []
        raise
    changes = repository.changes(log[0].commit)
    commits = [version.commit for version in reversed(log)]
    return [
        AgentVersion(version, parent, changes[version.commit])
        for version, parent in zip(reversed(log), [None, *commits[:-1]], strict=True)
    ]


def versions_index(
    agent: str, versions: list[AgentVersion], urls: dict[int, str]
) -> dict[str, Any]:
    """The agent's version history; `urls` gives the reference to each day's file."""
    diary: dict[int, str] = {}
    for found in versions:
        for change in found.changes:
            if entry := DIARY.fullmatch(change.path):
                if change.status == "D":
                    diary.pop(int(entry[1]), None)
                else:
                    diary[int(entry[1])] = urls[found.day]
    return {
        "agent": agent,
        "versions": [
            {
                "commit": found.version.commit,
                "time": found.version.time,
                "day": found.day,
                "level": found.version.level,
                "trigger": found.version.trigger,
                "subject": found.version.subject,
                "body": found.version.body,
                "changes": [asdict(change) for change in found.changes],
                "url": urls[found.day],
            }
            for found in versions
        ],
        "diary": [{"day": day, "url": url} for day, url in sorted(diary.items())],
    }


def agent_day(repository: Repository, agent: str, day: int, versions: list[AgentVersion]) -> dict:
    """The versions the agent committed on `day`, each with its diff (the episodic memory
    left out) and its readable state, and the diary entries they wrote."""
    trees = {found.version.commit: repository.tree(found.version.commit) for found in versions}
    written = {
        change.path
        for found in versions
        for change in found.changes
        if change.status != "D" and DIARY.fullmatch(change.path)
    }
    wanted = {
        blob
        for tree in trees.values()
        for path, blob in tree.items()
        if path in (POLICY, INSIGHTS) or SKILL.fullmatch(path) or path in written
    }
    texts = {blob: content.decode("utf-8") for blob, content in repository.blobs(wanted).items()}
    last = trees[versions[-1].version.commit]
    return {
        "agent": agent,
        "day": day,
        "versions": [
            {
                "commit": found.version.commit,
                "diff": repository.diff(
                    found.parent or EMPTY_TREE, found.version.commit, ".", f":(exclude){EPISODIC}"
                ),
                "state": _state(trees[found.version.commit], texts),
            }
            for found in versions
        ],
        "diary": [
            {"day": int(DIARY.fullmatch(path)[1]), "text": texts[last[path]]}
            for path in sorted(written)
            if path in last
        ],
    }


def _state(tree: dict[str, str], texts: dict[str, str]) -> dict[str, Any]:
    return {
        "policy": texts[tree[POLICY]] if POLICY in tree else None,
        "skills": {
            match[1]: texts[blob]
            for path, blob in sorted(tree.items())
            if (match := SKILL.fullmatch(path))
        },
        "insights": [json.loads(line) for line in texts[tree[INSIGHTS]].splitlines()]
        if INSIGHTS in tree
        else [],
        "diary": sorted(int(match[1]) for path in tree if (match := DIARY.fullmatch(path))),
    }
