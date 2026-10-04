"""Measures of a run, derived from its event log alone.

Every row belongs to a simulated day: an event counts on the day of its time. Amounts are in
credits. The last day of a run in progress is counted as far as the log goes, so its values
are partial until the day ends. Nothing here scores character: the measures count what
happened, and the held-out probes of `evaluation` are the only measure of traits.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations, permutations
from statistics import fmean, pstdev
from typing import Any

from analysis.run import RunData
from core.interaction import ActionKind, Event, EventKind, day_of, time_at

MEETINGS = ("work", "conversation")
"""The kinds of scene in which agents meet at a place."""
DECISIONS = tuple(str(kind) for kind in ActionKind)
ATTEMPTS = (*DECISIONS, "move")
"""What an agent can attempt and reality refuse: an action, or a move."""


@dataclass
class AgentDay:
    """One agent's day."""

    agent: str
    day: int
    balance: int
    """Balance after the agent's last balance change on or before this day (payment, living
    cost, clawback or credits given); its starting balance before any."""
    income: int = 0
    """Credits paid for the agent's accepted deliveries."""
    living_cost: int = 0
    """Credits charged as living cost."""
    clawed_back: int = 0
    """Credits taken back for defects discovered in the agent's earlier work."""
    claimed: int = 0
    """Tasks the agent claimed successfully."""
    delivered: int = 0
    """Deliveries accepted: they passed the acceptance checks and were paid."""
    failed: int = 0
    """Delivery attempts not accepted; the claim stays open until its deadline."""
    expired: int = 0
    """Claims of the agent that lapsed undelivered. A lapse is processed at the start of the
    day after the due day, so it counts on that day."""
    quality: float = 0.0
    """Sum of the true quality (share of hidden checks passed, from 0 to 1) of the accepted
    deliveries; their mean quality is `quality / delivered`."""
    defective: int = 0
    """Accepted deliveries declared complete with a true quality below 1, each of which
    carried a latent defect once paid; the agent's defect rate is `defective / delivered`."""
    defects_discovered: int = 0
    """Latent defects in the agent's earlier accepted work that came to light this day,
    announced to everyone."""
    clawbacks: int = 0
    """Payments taken back for those discovered defects."""
    utterances: int = 0
    """Things the agent said, at work or in conversation."""
    conversations: int = 0
    """Conversations the agent took part in from their start."""
    work_sessions: int = 0
    """Work sessions the agent took part in."""
    slots: dict[str, str | None] = field(default_factory=dict)
    """Where the agent was during each slot of the calendar, by slot name: the place it was
    at once the slot's moves were made. None for a slot the log has not reached."""
    decisions: dict[str, int] = field(default_factory=dict)
    """Decisions taken, by action kind; every kind is listed."""
    rejected: dict[str, int] = field(default_factory=dict)
    """Attempts reality refused, by attempted kind: every action kind and `move`."""
    ratings_received: int = 0
    """Ratings other agents gave the agent."""
    ratings_received_sum: int = 0
    """Sum of their scores (1 to 5); the mean is `ratings_received_sum / ratings_received`."""
    ratings_given: int = 0
    """Ratings the agent gave others."""
    ratings_given_sum: int = 0
    """Sum of their scores."""
    esteem: float | None = None
    """Esteem as published at the end of the day: the mean of the ratings received, each
    weighted by half for every half-life of its age. None if the agent has not been rated yet
    or the day has not ended."""
    evolution: dict[str, int] = field(default_factory=dict)
    """Evolution steps applied this night, by `level/trigger` (for example `L0/daily` or
    `L2/self`); only steps that happened are listed. Plain experience commits are not
    steps."""


@dataclass
class SocietyDay:
    """The whole town's day. Counts are the sums over agents of the same `AgentDay` fields
    unless said otherwise."""

    day: int
    conditions: dict[str, Any]
    """The conditions in force at the end of the day (or as far as the log goes)."""
    balance_mean: float
    """Mean of the agents' balances."""
    balance_min: int
    balance_max: int
    balance_sd: float
    """Population standard deviation of the balances. Every agent starts with the same
    balance and pays the same living cost, so this is also the spread of what they earned."""
    earnings_gini: float | None
    """Gini coefficient of cumulative net earnings (payments minus clawbacks since day 1):
    the mean absolute difference over all ordered pairs of agents divided by twice the mean;
    0 is perfect equality. None while nobody has earned anything. Balances themselves can be
    negative, for which the Gini coefficient is undefined."""
    esteem_mean: float | None
    """Mean esteem of the agents rated so far, as published at the end of the day."""
    tasks_posted: int = 0
    """Tasks posted to the board."""
    tasks_open: int = 0
    """Tasks open on the board at the end of the day (or as far as the log goes)."""
    claim_attempts: int = 0
    """Decisions to claim a task, successful or not: the demand for work."""
    claims_refused: int = 0
    """Claims reality refused: the task was taken first, the claimant already held a claim,
    or no such task was open (the log gives the reason only as text)."""
    contested: int = 0
    """Tasks claimed by several agents in the same turn, so that a draw decided."""
    tasks_retired: int = 0
    """Unclaimed tasks taken off the board after their shelf life."""
    claimed: int = 0
    delivered: int = 0
    failed: int = 0
    expired: int = 0
    quality: float = 0.0
    defective: int = 0
    quality_mean: float | None = None
    """Mean true quality of the day's accepted deliveries, `quality / delivered`; None if
    there were none."""
    defect_rate: float | None = None
    """Share of the day's accepted deliveries that carried a latent defect,
    `defective / delivered`; None if there were none."""
    defects_discovered: int = 0
    clawbacks: int = 0
    clawed_back: int = 0
    income: int = 0
    living_cost: int = 0
    utterances: int = 0
    conversations: int = 0
    """Conversations held (each counted once, not per participant)."""
    work_sessions: int = 0
    """Work sessions held (each counted once)."""
    ratings: int = 0
    """Ratings given."""
    ratings_sum: int = 0
    decisions: dict[str, int] = field(default_factory=dict)
    evolution: dict[str, int] = field(default_factory=dict)


@dataclass
class Edge:
    """What one agent (`source`) and another (`target`) had to do with each other on a day.
    A row exists only for a pair with something to count."""

    day: int
    source: str
    target: str
    minutes: int = 0
    """Simulated minutes both spent in the same work session or conversation: the turns in
    which both were present times the turn length. Agents present at a scene's start stay
    until it ends or they leave it. Symmetric."""
    scenes: int = 0
    """Work sessions and conversations both took part in. Symmetric."""
    addressed: int = 0
    """Utterances `source` addressed to `target` by name."""
    heard: int = 0
    """Utterances by `source` that `target` heard, addressed to anyone."""
    ratings: int = 0
    """Ratings `source` gave `target`."""
    ratings_sum: int = 0
    """Sum of their scores."""


@dataclass(frozen=True)
class Measures:
    agents: list[AgentDay]
    """One row per agent and day, by day and then in the agents' configured order."""
    society: list[SocietyDay]
    """One row per day."""
    graph: list[Edge]
    """Directed rows by day, source and target."""


@dataclass
class _Scene:
    kind: str
    day: int
    start: int
    participants: list[str]
    last: int
    turns: int | None = None
    left: dict[str, int] = field(default_factory=dict)


def measure(run: RunData) -> Measures:
    """The measures of every day of `run` that has begun."""
    config, agents = run.config, run.agents
    environment, simulation = config["environment"], config["simulation"]
    calendar = simulation["calendar"]
    turn = simulation["scenes"]["turn_minutes"]
    location = {
        agent: place["id"] for place in environment["places"] for agent in place["residents"]
    }
    starting = {
        agent: own["initial_balance"]
        for agent, own in environment.get("circumstances", {}).items()
        if own.get("initial_balance") is not None
    }
    balance = {agent: starting.get(agent, environment["initial_balance"]) for agent in agents}
    earnings = dict.fromkeys(agents, 0)
    conditions = dict(environment["conditions"])
    open_tasks: set[str] = set()
    scenes: dict[str, _Scene] = {}
    edges: dict[tuple[int, str, str], Edge] = {}
    rows: list[AgentDay] = []
    society: list[SocietyDay] = []
    by_day: dict[int, list[Event]] = defaultdict(list)
    for event in run.events:
        by_day[day_of(event.time)].append(event)
    end = run.events[-1].time if run.events else 0

    def edge(day: int, source: str, target: str) -> Edge:
        return edges.setdefault((day, source, target), Edge(day, source, target))

    for day in range(1, run.last_day + 1):
        today = {
            agent: AgentDay(
                agent,
                day,
                balance[agent],
                slots={slot["name"]: None for slot in calendar["slots"]},
                decisions=dict.fromkeys(DECISIONS, 0),
                rejected=dict.fromkeys(ATTEMPTS, 0),
            )
            for agent in agents
        }
        town: Counter[str] = Counter()
        slots = [(slot["name"], time_at(day, slot["start"])) for slot in calendar["slots"]]
        for event in by_day[day]:
            _locate(slots, event.time, today, location)
            payload, actor = _current(event), event.actor
            if event.scene in scenes:
                scenes[event.scene].last = event.time
            match event.kind:
                case EventKind.MOVE:
                    location[actor] = payload["destination"]
                case EventKind.SPEECH:
                    today[actor].utterances += 1
                    for listener in event.audience:
                        edge(day, actor, listener).heard += 1
                    if payload["to"] is not None:
                        edge(day, actor, payload["to"]).addressed += 1
                case EventKind.LEFT:
                    scenes[event.scene].left[actor] = event.time
                case EventKind.TASK_POSTED:
                    open_tasks.add(payload["task"]["id"])
                    town["tasks_posted"] += 1
                case EventKind.TASK_CLAIMED:
                    open_tasks.discard(payload["task_id"])
                    for worker in payload["workers"]:
                        today[worker].claimed += 1
                case EventKind.TASK_EXPIRED:
                    open_tasks.add(payload["task_id"])
                    for worker in payload["workers"]:
                        today[worker].expired += 1
                case EventKind.TASK_RETIRED:
                    open_tasks.discard(payload["task_id"])
                    town["tasks_retired"] += 1
                case EventKind.WORK_SUBMITTED:
                    if payload["accepted"]:
                        today[actor].delivered += 1
                    else:
                        today[actor].failed += 1
                case EventKind.WORK_ASSESSED if payload["accepted"]:
                    today[actor].quality += payload["quality"]
                    today[actor].defective += (
                        payload["quality"] < 1 and payload["declaration"] == "complete"
                    )
                case EventKind.PAYMENT:
                    today[payload["agent"]].income += payload["amount"]
                    earnings[payload["agent"]] += payload["amount"]
                    balance[payload["agent"]] = payload["balance"]
                case EventKind.CREDITS_GIVEN:
                    balance.update(payload["balances"])
                case EventKind.LIVING_COST:
                    today[payload["agent"]].living_cost += payload["amount"]
                    balance[payload["agent"]] = payload["balance"]
                case EventKind.CLAWBACK:
                    row = today[payload["agent"]]
                    row.clawbacks += 1
                    row.clawed_back += payload["amount"]
                    earnings[payload["agent"]] -= payload["amount"]
                    balance[payload["agent"]] = payload["balance"]
                case EventKind.DEFECT_DISCOVERED:
                    today[payload["worker"]].defects_discovered += 1
                case EventKind.RATING:
                    rater, target, score = payload["rater"], payload["target"], payload["score"]
                    today[target].ratings_received += 1
                    today[target].ratings_received_sum += score
                    today[rater].ratings_given += 1
                    today[rater].ratings_given_sum += score
                    edge(day, rater, target).ratings += 1
                    edge(day, rater, target).ratings_sum += score
                case EventKind.ESTEEM_UPDATED:
                    for agent, esteem in payload["esteem"].items():
                        today[agent].esteem = esteem
                case EventKind.ACTION_REJECTED:
                    kind = payload["attempt"]["kind"]
                    today[actor].rejected[kind] += 1
                    town["claims_refused"] += kind == ActionKind.CLAIM_TASK
                case EventKind.INTERVENTION:
                    conditions = dict(payload["conditions"])
                case EventKind.DECISION:
                    today[actor].decisions[payload["action"]["kind"]] += 1
                case EventKind.DRAW:
                    town["contested"] += 1
                case EventKind.EVOLUTION:
                    step = f"{payload['level']}/{payload['trigger']}"
                    evolution = today[payload["agent"]].evolution
                    evolution[step] = evolution.get(step, 0) + 1
                case EventKind.SCENE_STARTED if payload["kind"] in MEETINGS:
                    participants = list(payload["participants"])
                    scenes[event.scene] = _Scene(
                        payload["kind"], day, event.time, participants, event.time
                    )
                    town[f"{payload['kind']}_scenes"] += 1
                    for agent in participants:
                        if payload["kind"] == "work":
                            today[agent].work_sessions += 1
                        else:
                            today[agent].conversations += 1
                case EventKind.SCENE_ENDED if event.scene in scenes:
                    scenes[event.scene].turns = payload["turns"]
        _locate(
            slots, end + 1 if day == run.last_day else time_at(day + 1, "00:00"), today, location
        )
        for row in today.values():
            row.balance = balance[row.agent]
        rows += today.values()
        society.append(_society(day, list(today.values()), town, conditions, open_tasks, earnings))

    for scene in scenes.values():
        turns = scene.turns or (scene.last - scene.start) // turn + 1
        present = {
            agent: (scene.left[agent] - scene.start) // turn + 1 if agent in scene.left else turns
            for agent in scene.participants
        }
        for first, second in combinations(scene.participants, 2):
            together = min(present[first], present[second]) * turn
            for source, target in ((first, second), (second, first)):
                tie = edge(scene.day, source, target)
                tie.minutes += together
                tie.scenes += 1

    order = {agent: index for index, agent in enumerate(agents)}
    graph = sorted(edges.values(), key=lambda e: (e.day, order[e.source], order[e.target]))
    return Measures(rows, society, graph)


def _current(event: Event) -> dict[str, Any]:
    """The payload of `event` in the present shape. A log recorded before tasks had parts reads
    as what it meant then: a task had one worker, the claimant or the `agent` whose claim
    lapsed, and a delivery, always declared complete, was accepted when it `passed`."""
    payload = event.payload
    match event.kind:
        case EventKind.TASK_CLAIMED if "workers" not in payload:
            return {**payload, "workers": [event.actor]}
        case EventKind.TASK_EXPIRED if "workers" not in payload:
            return {**payload, "workers": [payload["agent"]]}
        case EventKind.WORK_SUBMITTED | EventKind.WORK_ASSESSED if "accepted" not in payload:
            return {**payload, "accepted": payload["passed"], "declaration": "complete"}
    return payload


def _locate(
    slots: list[tuple[str, int]],
    time: int,
    today: dict[str, AgentDay],
    location: dict[str, str],
) -> None:
    """Record where everyone is for each slot in `slots` (name, start) that started before
    `time`, every move at its start having been applied, and drop it from `slots`."""
    while slots and slots[0][1] < time:
        name, _ = slots.pop(0)
        for agent, row in today.items():
            row.slots[name] = location[agent]


def _society(
    day: int,
    rows: list[AgentDay],
    town: Counter,
    conditions: dict[str, Any],
    open_tasks: set[str],
    earnings: dict[str, int],
) -> SocietyDay:
    balances = [row.balance for row in rows]
    esteems = [row.esteem for row in rows if row.esteem is not None]
    total = SocietyDay(
        day=day,
        conditions=conditions,
        balance_mean=fmean(balances),
        balance_min=min(balances),
        balance_max=max(balances),
        balance_sd=pstdev(balances),
        earnings_gini=gini(list(earnings.values())),
        esteem_mean=fmean(esteems) if esteems else None,
        tasks_posted=town["tasks_posted"],
        tasks_open=len(open_tasks),
        claims_refused=town["claims_refused"],
        contested=town["contested"],
        tasks_retired=town["tasks_retired"],
        conversations=town["conversation_scenes"],
        work_sessions=town["work_scenes"],
    )
    for row in rows:
        for name in (
            "claimed",
            "delivered",
            "failed",
            "expired",
            "quality",
            "defective",
            "defects_discovered",
            "clawbacks",
            "clawed_back",
            "income",
            "living_cost",
            "utterances",
        ):
            setattr(total, name, getattr(total, name) + getattr(row, name))
        total.ratings += row.ratings_given
        total.ratings_sum += row.ratings_given_sum
        total.decisions = dict(Counter(total.decisions) + Counter(row.decisions))
        total.evolution = dict(Counter(total.evolution) + Counter(row.evolution))
    total.decisions = {kind: total.decisions.get(kind, 0) for kind in rows[0].decisions}
    total.claim_attempts = total.decisions[ActionKind.CLAIM_TASK]
    if total.delivered:
        total.quality_mean = total.quality / total.delivered
        total.defect_rate = total.defective / total.delivered
    return total


def gini(values: list[int]) -> float | None:
    """The Gini coefficient of non-negative `values`: the mean absolute difference over all
    ordered pairs divided by twice the mean; None if the mean is 0."""
    mean = fmean(values)
    if not mean:
        return None
    differences = sum(abs(a - b) for a, b in permutations(values, 2))
    return differences / (2 * len(values) ** 2 * mean)
