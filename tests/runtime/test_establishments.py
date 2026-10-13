"""A run of the firm town (`experiments/configs/firm.yaml`) with every reply scripted: jobs
are posted on the firm's job sheet and taken by its people, the foreman is paid for them and
pays the wages, the board at the Workshop says the firm has a place to fill, a freelancer asks
for it and is taken on, a member of staff gives notice and the newcomer is dismissed, every
step told in the town's words and measured by the analysis."""

import re
from pathlib import Path
from typing import Any

from analysis import measure, read_run
from core.agent.evolution import Evolver
from core.interaction import EventKind, card, day_of
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import LLMRequest, RecordingClient, ScriptedClient
from infrastructure.storage import RunDirectory, RunStatus
from runtime.simulation import Setup, Simulation
from tasks.coding import BANK, CodingTaskProvider
from tests.core.agent.test_prompts import choices, offered
from tests.core.environment.test_trades import GUARDS
from tests.runtime.test_simulation import BY_ENTRY_POINT, SOLUTIONS, Script, events

FIRM = Path(__file__).parents[2] / "experiments" / "configs" / "firm.yaml"
PLANS = {
    "Mei": {"morning": "Ostrander & Co.", "afternoon": "Ostrander & Co."},
    "Tomas": {"morning": "Ostrander & Co.", "afternoon": "Ostrander & Co."},
    "Aisha": {"morning": "the Workshop", "afternoon": "Ostrander & Co."},
}
"""Where each resident spends every day: Aisha calls at the firm in the afternoons."""


class Townsfolk(Script):
    """The firm town's people. Aisha asks for the place at the firm on the first morning;
    Mei takes her on when the card offers it; Tomas gives notice on the second day; Mei
    dismisses Aisha on the third. Otherwise everyone takes the first job on its sheet and
    hands in the reference solution, and nobody talks."""

    def __call__(self, request: LLMRequest) -> str | dict[str, Any]:
        if request.metadata["purpose"] != "act":
            return super().__call__(request)
        self.requests.append(request)
        agent, time = request.metadata["agent"], request.metadata["time"]
        day, can, prompt = day_of(time), offered(request), request.messages[-1].content
        thought = {"thought": f"secret-{agent}-{time}"}
        if card.DECIDE in can:
            parts = [part for part in choices(request, card.DECIDE) if part != card.PLAN]
            plan = {part: PLANS[agent].get(part, "home") for part in parts}
            return {**thought, "do": card.DECIDE, **plan, card.PLAN: "As planned."}
        if card.ASK_FOR_PLACE in can and agent == "Aisha" and day == 1:
            return {**thought, "do": card.ASK_FOR_PLACE, card.AT: "Ostrander & Co."}
        if card.TAKE_ON in can:
            return {**thought, "do": card.TAKE_ON, card.WHO: "Aisha"}
        if card.GIVE_NOTICE in can and agent == "Tomas" and day == 2:
            return {**thought, "do": card.GIVE_NOTICE}
        if card.DISMISS in can and day == 3 and "Aisha" in choices(request, card.DISMISS)[card.WHO]:
            return {**thought, "do": card.DISMISS, card.WHO: "Aisha"}
        if card.HAND_IN in can:
            task = BY_ENTRY_POINT[re.search(r"defines `(\w+)`", prompt)[1]]
            solution = SOLUTIONS[task]["reference"]
            told = {card.AS: "finished", card.TELLING: "Done."}
            return {**thought, "do": card.HAND_IN, card.CODE: solution, **told}
        if card.TAKE in can:
            return {**thought, "do": card.TAKE, card.JOB: choices(request, card.TAKE)[card.JOB][0]}
        if card.MARK in can:
            met = re.search(r"spent time with (.+?)\. ", prompt)[1].replace(" and ", ", ")
            marks = [{"who": peer, "mark": 4, "because": "We met."} for peer in met.split(", ")]
            return {**thought, "do": card.MARK, card.MARKS: marks}
        return {**thought, "do": card.CARRY_ON}


async def test_a_firm_posts_pays_hires_and_dismisses_through_its_days(tmp_path):
    config = load_config(FIRM, ExperimentConfig)
    run = RunDirectory.create(tmp_path, "firm", 1, config=config, code_revision="test")
    script = Townsfolk()
    setup = Setup(
        simulation=config.simulation,
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolver=Evolver(config.evolution),
        providers={"programming": CodingTaskProvider(BANK)},
        client=RecordingClient(ScriptedClient(script), run.llm_calls_path),
    )
    assert await Simulation.create(run, setup).run() is RunStatus.COMPLETED
    log = events(run)

    # The firm's sheet gets its own postings, seen by its people there, and its clients pay
    # the foreman; the board at the Workshop says the firm has a place to fill.
    posted = [e for e in log if e.kind is EventKind.TASK_POSTED]
    sheet = [e for e in posted if e.payload["task"]["sheet"] == "ostrander"]
    assert sheet and all(
        e.text.startswith("A new notice on Ostrander & Co.'s job sheet") for e in sheet
    )
    assert set(sheet[0].audience) == {"Mei", "Tomas"}  # the firm's people there, before Aisha
    paid = [e for e in log if e.kind is EventKind.PAYMENT]
    assert paid and all(e.payload["agent"] == "Mei" for e in paid if e.payload.get("workers"))
    prompts = [r.messages[-1].content for r in script.requests]
    vacancy = (
        "Ostrander & Co. has a place for a programmer at $30 a day; anyone without a place "
        "may ask for it"
    )
    assert any(vacancy in prompt for prompt in prompts)
    assert any("The notices here are on Ostrander & Co.'s job sheet" in p for p in prompts)
    known = script.requests[0].messages[0].content
    firm = "a firm doing programming jobs, with a job sheet of its own for its people and Mei"
    assert f"{firm} as foreman" in known
    assert "Some work places are firms" in known

    # Careers: asked for, taken on, notice given, dismissed; the wage follows attendance.
    careers = [
        (e.kind, e.payload.get("applicant", e.payload.get("agent")), day_of(e.time))
        for e in log
        if e.kind in (EventKind.APPLIED, EventKind.HIRED, EventKind.RESIGNED, EventKind.DISMISSED)
    ]
    assert careers == [
        (EventKind.APPLIED, "Aisha", 1),
        (EventKind.HIRED, "Aisha", 1),
        (EventKind.RESIGNED, "Tomas", 2),
        (EventKind.DISMISSED, "Aisha", 3),
    ]
    wages = [(day_of(e.time), e.payload["agent"]) for e in log if e.kind is EventKind.WAGE_PAID]
    # Dismissed on the third morning, Aisha calls at the firm that afternoon as a visitor and
    # is paid nothing for the day.
    assert wages == [(1, "Tomas"), (1, "Aisha"), (2, "Tomas"), (2, "Aisha")]
    measured = measure(read_run(run.root))
    rows = {(row.agent, row.day): row for row in measured.agents}
    assert [rows["Aisha", d].position for d in (1, 2, 3)] == ["staff", "staff", "freelance"]
    assert [rows["Tomas", d].position for d in (1, 2, 3)] == ["staff", "freelance", "freelance"]
    assert all(rows["Mei", d].position == "foreman" for d in (1, 2, 3))
    assert rows["Tomas", 1].wages_received == 30 and rows["Tomas", 1].attended == 1
    assert (
        rows["Mei", 1].wages_paid == 60 and rows["Aisha", 1].applied == rows["Aisha", 1].hired == 1
    )
    assert rows["Tomas", 2].resigned == 1 and rows["Aisha", 3].dismissed == 1
    society = {day.day: day for day in measured.society}
    assert (society[1].wages, society[1].attendance, society[1].hires) == (60, 2, 1)
    assert (society[2].notices, society[3].dismissals) == (1, 1)
    balances = {
        agent: config.environment.starting_balance(agent) for agent in ("Mei", "Tomas", "Aisha")
    }
    for event in log:
        p = event.payload
        if event.kind in (EventKind.PAYMENT, EventKind.LIVING_COST, EventKind.CLAWBACK):
            balances[p["agent"]] = p["balance"]
        elif event.kind in (EventKind.CREDITS_GIVEN, EventKind.WAGE_PAID):
            balances.update(p["balances"])
    assert balances == {row.agent: row.balance for row in measured.agents if row.day == 3}

    # Nothing anyone read steers or shows the machinery.
    sent = {line for r in script.requests for m in r.messages for line in m.content.splitlines()}
    assert not {line for line in sent if any(guard.search(line) for guard in GUARDS)}
