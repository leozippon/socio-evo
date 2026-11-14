"""Checkpoint-grounded AutoResearch comparison; run on the host that owns the run data.

python -m analysis.research --town RUN --academy RUN --out /REMOTE/comparison.json
Token counts describe retained records, not a provider invoice or reconstructed lost work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from agent.directory import TRACE
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, read_jsonl
from world.config import ResearchSettings


def usage(paths: list[Path], *, judge: bool = False) -> dict:
    counts = {"requests": 0, "replies": 0, "replies_missing_usage": 0, "missing_trace_files": 0}
    fields = ("prompt_tokens", "completion_tokens", "cached_prompt_tokens", "reasoning_tokens")
    totals, reports = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0)
    for path in paths:
        if not path.exists():
            counts["missing_trace_files"] += 1
            continue
        for record in read_jsonl(path):
            counts["requests"] += int(judge or record["kind"] == "request")
            reply = (
                record.get("response") if judge else record if record["kind"] == "reply" else None
            )
            if reply is None:
                continue
            counts["replies"] += 1
            token_usage = reply.get("usage")
            counts["replies_missing_usage"] += int(token_usage is None)
            for field in fields:
                if token_usage and token_usage.get(field) is not None:
                    totals[field] += token_usage[field]
                    reports[field] += 1
    return (
        counts
        | {field: totals[field] if reports[field] else None for field in fields}
        | {"usage_reports": reports}
    )


def summarize(root: Path) -> dict:
    run = RunDirectory.open(root)
    config = yaml.safe_load(run.config_path.read_text())
    research = config["town"].get("research")
    if not research:
        raise ValueError(f"{root} is not a shared research run")
    day = run.latest_checkpoint()
    checkpoint = json.loads(run.checkpoint_path(day).read_text()) if day is not None else None
    stages = []
    repo = Repository(root / "research")
    for scheduled in ResearchSettings.model_validate(research).stages_through(config["days"]):
        stage = scheduled.model_dump()
        if day is None or stage["day"] > day:
            stages.append({"stage": stage["id"], "day": stage["day"], "status": "pending"})
            continue
        record = json.loads(
            repo._git("show", f"{checkpoint['research']}:records/milestone-{stage['id']}.json")
        )
        if record["status"] == "reviewed":
            rubric = json.loads((root / record["audit"] / "input.json").read_text())["rubric"]
            record["rubric_sha256"] = hashlib.sha256(rubric.encode()).hexdigest()
        stages.append(record)
    actors = [run.agent_dir(resident["name"]) / TRACE for resident in config["residents"]]
    protocol = {key: config[key] for key in ("llm", "runtime", "days")}
    protocol.update(
        research={key: value for key, value in research.items() if key != "gpus"},
        seed=config["town"]["seed"],
    )
    fingerprint = hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    return {
        "protocol_sha256": fingerprint,
        "gpu_assignment": research.get("gpus"),
        "run": str(root.resolve()),
        "name": config["name"],
        "status": run.read_manifest().status.value,
        "completed_day": day,
        "planned_days": config["days"],
        "population": len(actors),
        "seed": config["town"]["seed"],
        "external_services": config["town"].get("external_services", False),
        "actor_model": config["llm"]["model"],
        "judge_model": (research.get("judge") or {}).get("model"),
        "checkpoint_revision": checkpoint["research"] if checkpoint else None,
        "milestones": stages,
        "milestone_rewards": sum(stage.get("reward_total", 0) for stage in stages),
        "resident_money": sum(r["inventory"]["money"] for r in checkpoint["residents"].values())
        if checkpoint
        else None,
        "actor_usage": usage(actors),
        "judge_usage": usage(
            sorted((root / "research_reviews").glob("*/*/attempts.jsonl")), judge=True
        ),
    }


def compare(town: Path, academy: Path) -> dict:
    arms = {"town": summarize(town), "academy": summarize(academy)}
    if arms["town"]["external_services"] or not arms["academy"]["external_services"]:
        raise ValueError("--town and --academy must name their respective service conditions")
    if arms["town"]["protocol_sha256"] != arms["academy"]["protocol_sha256"]:
        raise ValueError("paired actor/judge/research protocol, runtime or seed mismatch")
    a = {stage["stage"]: stage for stage in arms["academy"]["milestones"]}
    differences = []
    for t in arms["town"]["milestones"]:
        other = a.get(t["stage"], {})
        if t.get("status") == other.get("status") == "reviewed":
            if t["rubric_sha256"] != other["rubric_sha256"]:
                raise ValueError(f"paired runs used different judge rubrics for {t['stage']}")
        if (
            t.get("score") is not None
            and other.get("score") is not None
            and t["day"] == other["day"]
        ):
            differences.append(
                {
                    "stage": t["stage"],
                    "day": t["day"],
                    "town_minus_academy": t["score"] - other["score"],
                }
            )
    return {
        "arms": arms,
        "score_differences": differences,
        "notes": [
            "One society per arm is a pilot; residents are not independent replicates.",
            "Milestones and money use the latest completed checkpoint; pending is not zero.",
            "Actor usage sums retained traces for every resident, including service occupations; "
            "resume can discard unsaved traces, so these are not all historically billed tokens.",
            "Judge usage includes every persisted attempt, including failed and replayed stages. "
            "Usage can extend beyond the latest checkpoint; absent provider counts remain null.",
            "No monetary API cost, confidence interval or significance test is inferred.",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--town", type=Path, required=True)
    parser.add_argument("--academy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.town, args.academy)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    staging = args.out.with_suffix(args.out.suffix + ".tmp")
    staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    staging.replace(args.out)
    print(f"Research comparison written to {args.out}")


if __name__ == "__main__":
    main()
