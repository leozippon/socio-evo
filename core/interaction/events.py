"""Events, the immutable record of what happened, and percepts, a witness's view of one."""

import re
from enum import StrEnum

from pydantic import Field, JsonValue, NonNegativeInt

from core.interaction.time import SimTime
from infrastructure.config import StrictModel


class EventKind(StrEnum):
    ACTIVITY_ENTERED = "activity_entered"
    ACTIVITY_LEFT = "activity_left"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_CANCELLED = "tool_cancelled"
    ACTIVITY_FEEDBACK = "activity_feedback"
    CONVERSATION_MESSAGE = "conversation_message"
    CONVERSATION_READ = "conversation_read"
    CODE_HANDOFF = "code_handoff"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    GOAL_UPDATED = "goal_updated"
    DISCUSSION = "discussion"
    SUBMISSION_PENDING = "submission_pending"
    """The single vocabulary of event kinds."""

    DAY_STARTED = "day_started"
    DAY_ENDED = "day_ended"
    MOVE = "move"
    SPEECH = "speech"
    SPEECH_UNHEARD = "speech_unheard"
    """A private remark as the others present perceive it: who spoke to whom, not the words."""
    LEFT = "left"
    """A conversation left, the leaver staying at the place: what leaving meant in logs
    recorded before it meant going home, which is now a `move`."""
    TASK_POSTED = "task_posted"
    TASK_PROPOSED = "task_proposed"
    """A proposal to take a two-person task together; private to the two."""
    TASK_APPLIED = "task_applied"
    """An application for a two-person task, for the board to pair; private to the applicant."""
    OFFER_ENDED = "offer_ended"
    """An open proposal or application that ended without its maker taking that task with the
    one it named: withdrawn because its maker took a task or made another, because the task
    went to others or its client withdrew it, or lapsed at the day's end; private to the
    proposer and the partner, or to the applicant."""
    TASK_CLAIMED = "task_claimed"
    """A task taken: claimed alone, taken up together, or given to a pair by the board."""
    TASK_EXPIRED = "task_expired"
    """A task not completed by its deadline; nothing is paid and it returns to the board."""
    TASK_RETIRED = "task_retired"
    """An unclaimed task taken off the board after its shelf life; truth-only."""
    TASK_REPLACEMENT_UNAVAILABLE = "task_replacement_unavailable"
    """The finite issue pool could not supply a same-worker-count replacement."""
    TASK_WITHDRAWN = "task_withdrawn"
    """A task its client withdrew, from the board or from its workers, with nothing more paid
    for it; private to its workers, truth-only for a task nobody had taken."""
    COMMAND_EXECUTED = "command_executed"
    WORK_CHECKED = "work_checked"
    WORK_DELAYED = "work_delayed"
    """A solution run against a part's acceptance checks without delivery; private."""
    WORK_SUBMITTED = "work_submitted"
    """A delivery of a part and its public result, as witnesses see it."""
    WORK_ASSESSED = "work_assessed"
    """The true quality of a delivered part and what its worker knew; truth-only."""
    DESK = "desk"
    """What is still on a worker's desk at night, once everyone is home: its job, when it is
    due, and of each part whether it is in and what the worker last saw of it; private to the
    worker."""
    PAYMENT = "payment"
    CREDITS_GIVEN = "credits_given"
    LIVING_COST = "living_cost"
    DEFECT_DISCOVERED = "defect_discovered"
    CLAWBACK = "clawback"
    RATING = "rating"
    VOTE = "vote"
    """An answer given to the clerk at a meeting; truth-only."""
    WAGE_PAID = "wage_paid"
    """A day's wage paid by a foreman to a member of staff present at the firm that day;
    private to the two."""
    APPLIED = "applied"
    """A resident asked for the place a firm has to fill; private to it and the foreman."""
    HIRED = "hired"
    """A foreman took an applicant on; witnessed at the firm and by the applicant."""
    APPLICATION_ENDED = "application_ended"
    """An asking for a firm's place that ended because the firm filled its last place, told by
    the clerk; private to the one who asked."""
    DISMISSED = "dismissed"
    """A foreman dismissed a member of staff; witnessed at the firm and by the dismissed."""
    RESIGNED = "resigned"
    """A member of staff gave notice, leaving at the day's end; witnessed at the firm and by
    the foreman."""
    ESTEEM_UPDATED = "esteem_updated"
    ACTION_REJECTED = "action_rejected"
    """An action reality could not honour; private to the actor, nothing changed."""
    ANNOUNCEMENT = "announcement"
    INTERVENTION = "intervention"
    DECISION = "decision"
    """An agent's private thought and chosen action, recorded before it is executed; truth-only."""
    LAPSE = "lapse"
    """A moment in which an agent did nothing, or a night step it skipped, because no valid
    reply of its could be obtained, with how each attempt failed; truth-only."""
    DRAW = "draw"
    """The random order in which simultaneous claims on a task are taken; told to the claimants."""
    EVOLUTION = "evolution"
    SCENE_STARTED = "scene_started"
    SCENE_ENDED = "scene_ended"


class Percept(StrictModel):
    """A witness's view of an event: every event field except `payload`, `audience` and
    `personal`, with the text as that witness is told it."""

    seq: NonNegativeInt
    time: SimTime
    kind: EventKind
    actor: str | None = None
    place: str | None = None
    scene: str | None = None
    text: str
    task_id: str | None = Field(default=None, pattern=r"^task-\d+$")
    activity_id: str | None = None


class Event(StrictModel):
    """Something that happened, numbered by `seq` in the event log.

    `audience` holds the ids of the agents who witnessed it and is empty for truth-only
    events. `text` is what a witness perceives, naming everyone in it by name; `personal`
    holds, by agent id, the wording for each witness the text names, which says the same of
    that witness as `you` and is what it perceives instead (see `core.interaction.telling`).
    `payload` is structured truth for analysis and replay; only a whitelisted task
    identifier is projected for witnessed work events, never the rest of the payload.
    """

    seq: NonNegativeInt
    time: SimTime
    kind: EventKind
    actor: str | None = None
    place: str | None = None
    scene: str | None = None
    audience: tuple[str, ...] = ()
    text: str
    task_id: str | None = Field(default=None, pattern=r"^task-\d+$")
    activity_id: str | None = None
    personal: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    def percept(self, witness: str) -> Percept:
        """This event as `witness` perceives it: in its own wording, if it has one."""
        seen = self.model_dump(exclude={"payload", "audience", "personal"})
        seen["task_id"] = None
        activity = self.activity_id or self.payload.get("activity")
        seen["activity_id"] = (
            activity if witness in self.audience and isinstance(activity, str) else None
        )
        # Only a public routing identifier, never evaluation results or hidden tests.
        work_kinds = {
            EventKind.ACTIVITY_LEFT,
            EventKind.CODE_HANDOFF,
            EventKind.ACTIVITY_FEEDBACK,
            EventKind.TASK_POSTED,
            EventKind.TASK_CLAIMED,
            EventKind.TASK_PROPOSED,
            EventKind.TASK_APPLIED,
            EventKind.TASK_EXPIRED,
            EventKind.TASK_WITHDRAWN,
            EventKind.COMMAND_EXECUTED,
            EventKind.WORK_CHECKED,
            EventKind.WORK_DELAYED,
            EventKind.SUBMISSION_PENDING,
            EventKind.WORK_SUBMITTED,
            EventKind.DESK,
            EventKind.PAYMENT,
            EventKind.DEFECT_DISCOVERED,
            EventKind.CLAWBACK,
            EventKind.ACTION_REJECTED,
            EventKind.OFFER_ENDED,
        }
        task = self.task_id or self.payload.get("task_id")
        if witness in self.audience and self.kind in work_kinds and isinstance(task, str):
            if re.fullmatch(r"task-\d+", task):
                seen["task_id"] = task
        return Percept.model_validate({**seen, "text": self.personal.get(witness, self.text)})
