"""Exercise a complete conference review with the configured real external judge on Zenith.

Run with project credentials already in the environment. No resident model, GPU or formal
experiment is started. The output directory must be new and under Zenith project storage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pypdf import PdfWriter

from agent.directory import AgentDirectory
from experiments.config import PROJECT_ROOT, load_experiment
from ops.research.run_pair import remote_root
from world import research_conferences
from world.clock import ManualClock
from world.config import ConferenceVenue
from world.research import NoTasks
from world.world import World

PAPER = r"""
\documentclass{article}
\begin{document}
\title{A synthetic submission for conference protocol verification}
\maketitle
\begin{abstract}
This is an infrastructure test, not a scientific contribution or a real venue submission.
\end{abstract}
\section{Scope}
No experiment, dataset, novelty claim or performance measurement is presented.
The supplied source and readable PDF exercise submission freezing and review feedback.
This manuscript is intentionally inadequate for scientific acceptance.
\section{Limitations}
This test does not establish scientific quality, successful LaTeX compilation,
PDF/source equivalence, or independent reproduction.
\end{document}
"""


async def check(config_path: Path, output: Path) -> dict:
    config = load_experiment(config_path).town
    settings = config.research
    if settings is None or settings.judge is None:
        raise ValueError("The profile must configure an external judge")
    if not os.environ.get(settings.judge.api_key_env):
        raise ValueError("The judge credential environment variable is missing")
    # A tiny artificial timetable tests transitions, not any real conference calendar.
    start = datetime.combine(config.start_date, datetime.min.time(), tzinfo=UTC)
    venue = ConferenceVenue(
        id="protocol-check",
        title="Synthetic infrastructure check",
        scope="Protocol verification only; do not award scientific merit for this test.",
        abstract_at=start + timedelta(days=1),
        submission_at=start + timedelta(days=2),
        reviews_at=start + timedelta(days=3),
        rebuttal_at=start + timedelta(days=4),
        notification_at=start + timedelta(days=5),
        camera_ready_at=start + timedelta(days=6),
    )
    config = config.model_copy(
        update={
            "research": settings.model_copy(
                update={
                    "start_day": 1,
                    "pit": False,
                    "cycles": None,
                    "milestones": (),
                    "conferences": (venue,),
                    "domain": "conference protocol verification",
                    "judge": settings.judge.model_copy(update={"max_retries": 0}),
                }
            )
        }
    )
    output.mkdir(parents=True, exist_ok=False)
    for resident in config.residents:
        AgentDirectory.create(
            output / "agents" / resident.name,
            background="A synthetic infrastructure-test resident.",
        )
    world = World(config, output, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    (world.research.files / "paper.tex").write_text(PAPER)
    # A readable one-page PDF is enough for the desk's documented structural check.
    # No claim is made that it renders the supplied source.
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(world.research.files / "paper.pdf")
    world.research.repo.commit("Synthetic protocol manuscript", date=datetime.now(UTC))
    factory, calls = research_conferences.create_client, 0

    class CountedClient:
        def __init__(self, inner):
            self.inner = inner

        async def complete(self, request):
            nonlocal calls
            if calls >= 7:
                raise RuntimeError("Acceptance probe exhausted its seven-call API budget")
            calls += 1
            return await self.inner.complete(request)

    async def action(current, name, **args):
        return await research_conferences.ConferenceDesk(current.research).call(
            current,
            next(iter(current.residents.values())),
            {"action": name, "venue": venue.id, **args},
        )

    def moment(current, target):
        seconds = (target - current.research.simulated_now(current)).total_seconds()
        current.clock.set(current.clock.now() + int(seconds))

    def money(current):
        return {name: resident.inventory.money for name, resident in current.residents.items()}

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))

    research_conferences.create_client = lambda judge: CountedClient(factory(judge))
    try:
        await action(
            world,
            "register",
            title="Synthetic protocol check",
            abstract="Infrastructure verification; no scientific result claimed.",
        )
        await action(world, "submit")
        initial_money = money(world)
        moment(world, venue.reviews_at - timedelta(seconds=1))
        assert "reviews" not in (await action(world, "open"))["submissions"][0]
        assert calls == 0
        moment(world, venue.reviews_at)
        released = (await action(world, "open"))["submissions"][0]
        assert len(released["reviews"]) == calls == 3
        assert money(world) == initial_money
        (world.research.files / "rebuttal.md").write_text(
            "We acknowledge the reviewers' scientific concerns. This is solely a synthetic "
            "infrastructure probe; there are no empirical findings, novel methods or additional "
            "experiments. Do not reinterpret protocol execution as scientific merit."
        )
        await action(world, "rebuttal")
        before = world.snapshot()
        save("checkpoint-before-decision.json", before)
        moment(world, venue.notification_at)
        decided = (await action(world, "open"))["submissions"][0]
        assert calls == 7
        grant = decided["reward_per_resident"]
        expected = {name: value + grant for name, value in initial_money.items()}
        assert money(world) == expected
        after = world.snapshot()
        save("checkpoint-after-decision.json", after)
        for snapshot in (after, before):
            restored = World(config, output, NoTasks(), clock=ManualClock())
            restored.restore(snapshot)
            moment(restored, venue.notification_at)
            replay = (await action(restored, "open"))["submissions"][0]
            assert replay["decision"] == decided["decision"]
            assert money(restored) == expected
            assert calls == 7
        if decided["status"] == "accepted":
            await action(restored, "camera_ready")
        receipt = {
            "ok": True,
            "judge_calls": calls,
            "initial_reviews": 3,
            "updated_reviews": 3,
            "meta_decisions": 1,
            "restore_checks": 2,
            "status": decided["status"],
            "reward_per_resident": grant,
            "duplicate_grants": 0,
            "extra_calls_on_restore": 0,
            "real_venue_submission": False,
            "scientific_validation": False,
            "judge_model": settings.judge.model,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        save("receipt.json", receipt)
        return receipt
    except Exception as error:
        save(
            "failure.json",
            {
                "ok": False,
                "judge_calls": calls,
                "type": type(error).__name__,
                "message": str(error),
            },
        )
        raise
    finally:
        research_conferences.create_client = factory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "experiments/configs/ir-lab.yaml"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = remote_root(args.output)
    try:
        receipt = asyncio.run(check(args.config, output))
    except Exception as error:
        failure = output / "failure.json"
        count = json.loads(failure.read_text()).get("judge_calls", 0) if failure.exists() else 0
        print(json.dumps({"ok": False, "judge_calls": count, "status": type(error).__name__}))
        return 1
    print(
        json.dumps(
            {
                key: receipt[key]
                for key in ("ok", "judge_calls", "status", "restore_checks", "duplicate_grants")
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
