"""Event-driven activities. The seconds clock, not model/tool wall latency, orders effects."""

import asyncio
import hashlib
import json
import math
import shlex
from dataclasses import dataclass

from core.environment import PlaceKind
from core.environment.rejection import AssessmentUnavailable, Rejected
from core.interaction import (
    ClaimTask,
    Decision,
    EventKind,
    Observation,
    RunCommand,
    SubmitWork,
    clock_of,
    day_of,
)
from core.interaction.actions import Activity as Choice
from core.interaction.card import MayActivity
from infrastructure.llm import StructuredOutputError
from runtime.activities.model import (
    ACTIVITIES,
    ConversationActivity,
    EventQueue,
    Handoff,
    Invitation,
    Member,
    Message,
    MoveActivity,
    RestActivity,
    WorkActivity,
    at,
    clock,
    units,
)
from runtime.scenes import situations
from runtime.scenes.scene import _announce_draws, lapse


@dataclass
class PendingTool:
    activity: str
    action: Choice
    start: int
    end: int
    prepared: dict
    token: str = ""


class ActivityLoopError(RuntimeError):
    """An agent repeatedly chose zero-time transitions without doing any timed activity."""


class ActivityEngine:
    def __init__(self, simulation, state=None):
        self.sim, self.env = simulation, simulation.env
        self.timing = simulation.config.activity_timing
        state = state or {}
        self.activities = {
            key: ACTIVITIES[value["kind"]].model_validate(value)
            for key, value in state.get("activities", {}).items()
        }
        self.invitations = {
            key: Invitation.model_validate(value)
            for key, value in state.get("invitations", {}).items()
        }
        self.handoffs = {
            key: Handoff.model_validate(value) for key, value in state.get("handoffs", {}).items()
        }
        # Old checkpoints may contain doorstep waits. Workplaces now admit early arrivals.
        self.outside = {
            who: place
            for who, place in state.get("outside", {}).items()
            if self.env.world.places[place].kind != PlaceKind.WORK
        }
        for activity in self.activities.values():
            if (
                isinstance(activity, ConversationActivity)
                and self.env.world.places[activity.place].kind == PlaceKind.WORK
            ):
                activity.outside = False
        self.assessments = dict(state.get("assessments", {}))
        self.futures = {}
        self.pending: dict[str, PendingTool] = {}
        self.current: dict[str, str] = {}
        self.queue = EventQueue()
        self.daily_waiting = set()
        self.daily_life = dict(state.get("daily_life", {}))
        self.serial = state.get("serial", 0)
        self.now = 0
        self.end = 0
        self.transitions: dict[tuple[int, str], int] = {}
        self.selection_feedback = dict(state.get("selection_feedback", {}))
        self.rest_intents = dict(state.get("rest_intents", {}))
        self.rest_activities = dict(state.get("rest_activities", {}))
        if "rest_activities" not in state:
            for activity in self.activities.values():
                if isinstance(activity, RestActivity) and len(activity.members) == 1:
                    self.rest_activities[next(iter(activity.members))] = activity.id
        self.rest_requests = {}
        self.deferred_invitation_replies = dict(state.get("deferred_invitation_replies", {}))

    def state(self):
        return {
            "activities": {k: v.model_dump(mode="json") for k, v in self.activities.items()},
            "invitations": {k: v.model_dump(mode="json") for k, v in self.invitations.items()},
            "handoffs": {k: v.model_dump(mode="json") for k, v in self.handoffs.items()},
            "assessments": self.assessments,
            "daily_life": self.daily_life,
            "serial": self.serial,
            "outside": dict(self.outside),
            "selection_feedback": dict(self.selection_feedback),
            "rest_intents": dict(self.rest_intents),
            "rest_activities": dict(self.rest_activities),
            "deferred_invitation_replies": dict(self.deferred_invitation_replies),
        }

    def identifier(self, prefix):
        self.serial += 1
        return f"{prefix}-{self.serial}"

    def emit(self, kind, text, *, actor=None, audience=None, **payload):
        return self.env.emit(
            kind,
            text,
            time=self.now // 60,
            actor=actor,
            place=self.env.world.locations.get(actor),
            audience=audience if audience is not None else ([actor] if actor else []),
            scene=f"day-{day_of(self.now // 60):04d}/activities",
            payload={"sim_seconds": self.now, **payload},
        )

    def feedback(self, who, text, **payload):
        active = self.activities.get(self.current.get(who))
        if not active:
            self.selection_feedback[who] = text
        if active:
            active.feedback.setdefault(who, []).append(text)
        if isinstance(active, WorkActivity) and active.task_id:
            payload.setdefault("task_id", active.task_id)
        self.emit(
            EventKind.ACTIVITY_FEEDBACK,
            text,
            actor=who,
            activity=active.id if active else None,
            **payload,
        )

    def next_opening(self, place):
        return next(
            (
                at(day_of(self.now // 60), opening)
                for opening, _ in self.env.world.places[place].spans()
                if at(day_of(self.now // 60), opening) > self.now
            ),
            None,
        )

    def admit_waiters(self):
        for who, place in list(self.outside.items()):
            if self.now >= self.end or not self.env.world.places[place].is_open(
                clock_of(self.now // 60)
            ):
                continue
            activity = self.activities.get(self.current.get(who))
            if isinstance(activity, ConversationActivity) and activity.outside:
                continue  # Keep an ongoing doorway chat together when the doors open.
            if isinstance(activity, MoveActivity):
                continue  # Leaving the doorway is still a movement, not an admission.
            self.outside.pop(who)
            if isinstance(activity, RestActivity):
                self.leave(who, "The doors opened; you may enter.")
            self.env.firms.attend(who, place)
            self.feedback(
                who,
                f"The doors of {self.env.world.places[place].name} are open. You are now inside.",
                outside=False,
            )

    def arrive(self, who, destination):
        if self.sim.config.lunch_place:
            for invitation in self.invitations.values():
                if invitation.status == "pending" and who in invitation.confirmed:
                    self.queue.add(
                        max(
                            self.now,
                            invitation.start - self.travel_seconds(destination, invitation.place),
                        ),
                        "daily_choice",
                    )
        self.outside.pop(who, None)
        self.env.move(
            who,
            destination,
            time=self.now // 60,
            allow_closed=True,
            workplace_entry=self.venue_open(destination),
            sim_seconds=self.now,
        )
        closed = not self.venue_open(destination)
        self.leave(
            who,
            "Arrived outside the closed destination." if closed else "Arrived at the destination.",
        )
        if closed and self.now < self.end:
            self.outside[who] = destination
            opening = self.next_opening(destination)
            self.feedback(
                who,
                f"You are outside {self.env.world.places[destination].name}. "
                + (
                    f"The doors open at {clock(opening)}; choose rest, movement or a local chat. "
                    "entering and indoor work are unavailable before opening."
                    if opening
                    else "It will not reopen today; you may wait outside or move elsewhere."
                ),
                outside=True,
            )

    def venue_open(self, place, when=None):
        """Workplace access is independent of the hours for repository operations."""
        when = self.now if when is None else when
        p = self.env.world.places[place]
        if p.kind == PlaceKind.WORK:
            return "07:00" <= clock_of(when // 60) < "22:00"
        return p.is_open(clock_of(when // 60))

    def activity_closes(self, activity):
        if (
            isinstance(activity, WorkActivity)
            and self.env.world.places[activity.place].kind == PlaceKind.WORK
        ):
            return next(
                (
                    at(day_of(self.now // 60), end)
                    for end in ("12:00", "18:00")
                    if at(day_of(self.now // 60), end) > self.now
                ),
                self.end,
            )
        return self.close_at(activity.place)

    def venue_or_work_closed(self, who, place):
        if not self.venue_open(place):
            return True
        activity = self.activities.get(self.current.get(who))
        if (
            not isinstance(activity, WorkActivity)
            or self.env.world.places[place].kind != PlaceKind.WORK
        ):
            return False
        # End a work session at the coding boundary, but permit a new preparation-only
        # session afterward. Otherwise every boundary check would eject that session again.
        started = activity.members[who].start
        day = day_of(self.now // 60)
        return any(
            started < at(day, closing) <= self.now < at(day, reopening)
            for closing, reopening in (("12:00", "14:00"), ("18:00", "22:00"))
        )

    def close_at(self, place):
        if self.env.world.places[place].kind == PlaceKind.WORK:
            return self.end
        p = self.env.world.places[place]
        closing = p.closing(clock_of(self.now // 60))
        return min(self.end, at(day_of(self.now // 60), closing)) if closing else self.end

    def travel_seconds(self, origin, destination):
        a, b = self.env.world.places[origin], self.env.world.places[destination]
        return max(
            1, math.ceil((abs(a.x - b.x) + abs(a.y - b.y)) * self.timing.travel_seconds_per_unit)
        )

    def remaining(self, who):
        activity = self.activities[self.current[who]]
        closing = (
            self.end
            if isinstance(activity, ConversationActivity) and activity.outside
            else self.activity_closes(activity)
        )
        return max(0, min(activity.members[who].end, closing, self.end) - self.now)

    def can_code(self, who):
        place = self.env.world.places[self.env.world.locations[who]]
        text = clock_of(self.now // 60)
        return (
            who not in self.outside
            and place.kind == PlaceKind.WORK
            and place.is_open(text)
            and ("08:00" <= text < "12:00" or "14:00" <= text < "18:00")
        )

    def available(self, who):
        activity = self.activities.get(self.current.get(who))
        return activity is None or (
            isinstance(activity, RestActivity) and activity.wake_invitations
        )

    def work_access(self, who, activity):
        claim = self.env.board.claim_of(who)
        if activity.task_id and (claim is None or activity.task_id != claim.task.id):
            return False
        return who in activity.members or bool(
            activity.public and claim and claim.task.id == activity.task_id
        )

    def relay_session(self, task_id):
        """A relay owns the job's write permission, including older private sessions."""
        return next(
            (
                a
                for a in self.activities.values()
                if isinstance(a, WorkActivity)
                and a.public
                and a.mode == "relay"
                and a.task_id == task_id
                and a.status != "ended"
            ),
            None,
        )

    def people_within_earshot(self, place, outside):
        return tuple(
            p
            for p in self.env.world.occupants(place)
            if (p in self.outside) == outside
            and not isinstance(self.activities.get(self.current.get(p)), MoveActivity)
        )

    def conversation_access(self, who, activity):
        return (
            activity.status == "active"
            and (len(activity.participants) >= 2 or activity.spontaneous)
            and (who in self.outside) == activity.outside
            and self.env.world.locations[who] == activity.place
            and (activity.public or who in activity.invited)
            and (activity.outside or self.venue_open(activity.place))
        )

    def conversation_audience(self, activity):
        if activity.public and activity.spontaneous:
            return self.people_within_earshot(activity.place, activity.outside)
        return activity.participants

    def deferred_invitation_ids(self, who):
        return {
            ident
            for reply in self.deferred_invitation_replies.get(who, [])
            for ident in (reply["payload"].get("invitation"), reply["payload"].get("supersedes"))
            if ident
        }

    def deliver_invitation_replies(self, who):
        for reply in self.deferred_invitation_replies.pop(who, []):
            self.emit(
                EventKind.DISCUSSION,
                reply["text"],
                actor=reply["actor"],
                audience=[who],
                **reply["payload"],
                source_event_id=reply["source_event_id"],
                deferred_reply=True,
            )
        # A direct Work-to-Rest transition entered before the notifications were delivered.
        # Wake before the realtime resident consumes those percepts into memory.
        self.wake_rests()

    def invitation_ids(self, who):
        return [
            i.id
            for i in self.invitations.values()
            if i.status == "pending"
            and i.id not in self.deferred_invitation_ids(who)
            and who in i.invited
            and who not in i.declined
            and self.now <= i.grace_end
        ]

    def ready_for_invitation(self, who, invitation):
        if not self.available(who):
            return False
        activity = self.activities.get(self.current.get(who))
        return not (
            isinstance(activity, RestActivity)
            and activity.waiting_for
            and activity.waiting_for != invitation.id
        )

    def invitation_views(self, who, *, include_deferred=False):
        """Expose commitments and readiness without other residents' private work contents."""
        views = []
        for invitation in self.invitations.values():
            if not include_deferred and invitation.id in self.deferred_invitation_ids(who):
                continue
            if who not in (invitation.owner, *invitation.invited):
                continue
            status = invitation.status
            if status == "pending":
                status = (
                    "expired"
                    if self.now > invitation.grace_end
                    else "declined"
                    if who in invitation.declined
                    else "confirmed_waiting"
                    if who in invitation.confirmed
                    else "awaiting_response"
                )
            if status == "started" and invitation.conversation:
                conversation = self.activities.get(invitation.conversation)
                if conversation is None or conversation.status == "ended":
                    status = "ended"
            readiness = {}
            for person in dict.fromkeys((invitation.owner, *invitation.invited)):
                if person in invitation.declined:
                    readiness[person] = "declined"
                elif person not in invitation.confirmed:
                    readiness[person] = "awaiting_response"
                elif self.env.world.locations[person] != invitation.place or person in self.outside:
                    readiness[person] = "not_at_meeting"
                elif not self.ready_for_invitation(person, invitation):
                    readiness[person] = "busy_finish_current_operation_or_leave_activity"
                else:
                    readiness[person] = "ready"
            views.append(
                {
                    **invitation.model_dump(),
                    "status": status,
                    "readiness": readiness,
                    "start_clock": clock(invitation.start),
                    "grace_clock": clock(invitation.grace_end),
                    "your_confirmed": who in invitation.confirmed,
                    "seconds_until_start": max(0, invitation.start - self.now),
                    "depart_by": clock(
                        max(
                            0,
                            invitation.start
                            - self.travel_seconds(self.env.world.locations[who], invitation.place),
                        )
                    ),
                    "travel_seconds": self.travel_seconds(
                        self.env.world.locations[who], invitation.place
                    ),
                }
            )
        return views

    def activity_contract(self, who):
        active = self.activities.get(self.current.get(who))
        kind = active.kind if active else "selection"
        descriptions = {
            "selection": "Choose rest, movement, work, or a conversation. "
            "You may enter Work first, then claim a job there.",
            "rest": "You are resting until your chosen time.",
            "move": "You are travelling to your destination.",
            "work": "Use the work choices, switch to rest, or leave this activity.",
            "conversation": "Talk, wait, switch to rest, or leave this activity.",
        }
        return descriptions[kind]

    def clock_rules(self):
        return (
            "Choosing an activity takes no time. Each operation takes the time shown; "
            "its effects appear when it finishes and it must fit before the activity ends. "
            "You read new conversation messages to see their content."
        )

    def town_setting(self):
        """Town rules belong in the stable setting; current circumstances do not."""
        return "\n".join(
            [
                self.env.config.setting.backdrop,
                self.env.rules_view(),
                "You spend your time resting, moving, working, or in conversation. "
                "When free, choose an activity; while in one, continue it or leave before "
                "choosing another. Paused work keeps its progress. "
                "You can start or join a public conversation with people here without an "
                "invitation, or arrange a meeting for later. Invitations wait until you are free. "
                "Use help for instructions and the repository work guide for work details.",
                *(
                    [
                        "At noon everyone walks to lunch after finishing started operations "
                        "or travel; "
                        "evenings are free."
                    ]
                    if self.sim.config.lunch_place
                    else []
                ),
                self.clock_rules(),
                "Workplaces admit residents 07:00–22:00; coding hours are "
                "08:00–12:00 and 14:00–18:00. Repository work requires an assigned job "
                "and a Work activity at an open workplace. Outside coding hours, Work "
                "still allows notices, claiming, feedback, and arranging partners. "
                "At 22:00 you return home for the night.",
                *[
                    f"{p.name}: {p.kind.value}; "
                    + ("access 07:00–22:00" if p.kind == PlaceKind.WORK else f"open {p.spans()}")
                    for p in self.env.world.places.values()
                ],
            ]
        )

    def activity_help(self, who):
        """Deterministic instructions; never consume observations or pending messages."""
        from core.interaction.card import Card, form

        menu = self.menu(who)
        active = self.activities.get(self.current.get(who))
        sections = [
            "Activity help",
            self.current_facts(who),
            self.activity_contract(who),
            self.clock_rules(),
            "Rest ends at the chosen time today or tomorrow; tomorrow deadlines survive overnight. "
            "Social wake-ups offer you a choice when someone invites you or speaks nearby. "
            "Movement takes time according to distance. Work progress survives leaving; "
            "partners keep private repositories and exchange explicit code handoffs.",
            "For an invitation, accept, decline, or propose a later time. A changed time "
            "requires fresh confirmation. A confirmed meeting starts when at least two "
            "confirmed people are present and free, within its arrival grace period. "
            "At the meeting place, wait for the confirmed conversation to become ready.",
            "Your invitations: " + json.dumps(self.invitation_views(who, include_deferred=True)),
        ]
        if not menu.get("realtime"):
            sections.append("Tool costs in seconds: " + json.dumps(menu.get("costs", {})))
        if isinstance(active, WorkActivity):
            claim = self.env.board.claim_of(who)
            if claim:
                provider = self.env.providers[claim.task.trade]
                if callable(getattr(provider, "work_guide", None)):
                    sections.append(provider.work_guide(claim.task.parts[0]))
            else:
                sections.append("Take a job from the notice board to begin repository work.")
        sections.append(
            form(Card((MayActivity(layer="tool" if active else "selection", menu=menu),)).model)
        )
        return "\n\n".join(sections)

    def show_help(self, who):
        text = self.activity_help(who)
        activity = self.current.get(who)
        self.emit(
            EventKind.TOOL_STARTED,
            f"{who} requested activity help.",
            actor=who,
            activity=activity,
            tool="help",
            start=self.now / 60,
            end=self.now / 60,
        )
        self.feedback(who, text)
        self.emit(
            EventKind.TOOL_COMPLETED,
            f"{who} finished help.",
            actor=who,
            activity=activity,
            tool="help",
            start=self.now / 60,
            end=self.now / 60,
        )
        return text

    def current_facts(self, who):
        today = day_of(self.now // 60)
        period_end = next(
            (
                at(today, end)
                for start, end in (("08:00", "12:00"), ("14:00", "18:00"))
                if at(today, start) <= self.now < at(today, end)
            ),
            None,
        )
        next_start = next(
            (at(today, t) for t in ("08:00", "14:00") if at(today, t) > self.now), None
        )
        work_period = (
            f"OPEN, closes at {clock(period_end)}, {period_end - self.now} seconds remaining"
            if period_end
            else "CLOSED; "
            + (
                f"next opens at {clock(next_start)}"
                if next_start
                else "next opens tomorrow at 08:00"
            )
        )
        place = self.env.world.places[self.env.world.locations[who]]
        venue_open = self.venue_open(place.id)
        return (
            f"It is {clock(self.now)} on day {today}. "
            f"You are at {place.name}, {'outside' if who in self.outside else 'inside'}. "
            f"The venue is {'OPEN' if venue_open else 'CLOSED'}. "
            f"Town coding period is {work_period}. "
            f"Current location permits code work now: {self.can_code(who)}. "
            f"Today ends at {clock(self.end)}." + self.assessment_waiting(who)
        )

    def assessment_waiting(self, who):
        claim = self.env.board.claim_of(who)
        if claim is None or claim.task.id not in self.assessments:
            return ""
        entry = self.assessments[claim.task.id]
        due = entry["due"]
        timing = (
            f"First feedback is expected at {clock(due)}; checking may take longer."
            if self.now < due
            else "Checking is still pending; feedback will arrive when ready."
        )
        if entry.get("retry_at"):
            timing += f" The clerk will automatically retry at {clock(entry['retry_at'])}."
        return (
            f" Your job {claim.task.id} is awaiting background acceptance. {timing} "
            "It occupies your one-job slot while checking is pending."
        )

    def menu(self, who):
        place = self.env.world.locations[who]
        people = [p for p in self.env.agents if p != who]
        places = {
            p.name: p.id
            for p in self.env.world.places.values()
            if p.kind != PlaceKind.HOME or who in p.residents
        }
        common = {
            "people": people,
            "nearby_people": [
                p for p in self.people_within_earshot(place, who in self.outside) if p != who
            ],
            "places": places,
            "invitations": self.invitation_ids(who),
            "defer_invitations": [
                i for i in self.invitation_ids(who) if not self.invitations[i].conversation
            ],
            "accept_invitations": [
                i for i in self.invitation_ids(who) if who not in self.invitations[i].confirmed
            ],
            "ready_invitations": [
                i.id
                for i in self.invitations.values()
                if i.status == "pending"
                and i.id not in self.deferred_invitation_ids(who)
                and who in i.confirmed
                and self.now < i.grace_end
                and i.place == place
                and who not in self.outside
            ],
            "outside": who in self.outside,
        }
        if who not in self.current:
            moves = {
                name: ident
                for name, ident in places.items()
                if ident != place and self.now + self.travel_seconds(place, ident) <= self.end
            }
            return {
                **common,
                "moves": moves,
                "work": [
                    a.id
                    for a in self.activities.values()
                    if isinstance(a, WorkActivity)
                    and a.status != "ended"
                    and (a.place == place or not a.participants)
                    and who not in self.outside
                    and self.work_access(who, a)
                ],
                "conversations": [
                    a.id
                    for a in self.activities.values()
                    if isinstance(a, ConversationActivity) and self.conversation_access(who, a)
                ],
            }
        activity = self.activities[self.current[who]]
        if isinstance(activity, RestActivity | MoveActivity):
            return {**common, "tools": ["help"], "costs": {"help": 0}, "blocked": {}}
        if isinstance(activity, ConversationActivity):
            tools = [
                "help",
                "leave",
                "read",
                "reply",
                "wait",
                "invite",
                "invite_here",
                "accept",
                "decline",
                "defer",
            ]
        else:
            claim = self.env.board.claim_of(who)
            tools = ["help", "leave", "board", "feedback", "invite", "accept", "decline", "defer"]
            if claim is None:
                tools.append("claim")
            else:
                activity.task_id = claim.task.id
                common["partners"] = [p for p in claim.workers if p != who]
                provider = self.env.providers[claim.task.trade]
                if callable(getattr(provider, "work_guide", None)):
                    tools.append("guide")
                if self.can_code(who):
                    tools += ["read_code", "search", "diff"]
                    relay = self.relay_session(claim.task.id)
                    if (relay is None and activity.mode == "parallel") or (
                        (relay or activity).relay_owner == who
                    ):
                        tools += ["edit", "command", "test", "submit"]
                    if hasattr(provider, "export_handoff") and (
                        relay is None or relay.relay_owner == who
                    ):
                        tools.append("handoff")
                    if hasattr(provider, "apply_handoff"):
                        tools += ["apply_handoff", "decline_handoff"]
                common["handoffs"] = [
                    h.id
                    for h in self.handoffs.values()
                    if h.task_id == claim.task.id and h.recipient == who and h.status == "offered"
                ]
                if claim.task.id in self.assessments:
                    tools = [t for t in tools if t != "submit"]
            common["jobs"] = [listing.task.id for listing in self.env.board.listings.values()]
        remaining = self.remaining(who)
        costs = {name: self.minimum_cost(name) for name in tools}
        common.update(
            tools=[t for t in tools if costs[t] <= remaining],
            blocked={t: c for t, c in costs.items() if c > remaining},
            costs=costs,
            max_read_lines=self.timing.max_read_lines,
        )
        return common

    def minimum_cost(self, tool):
        return {
            "help": 0,
            "leave": 0,
            "claim": 0,
            "accept": 0,
            "decline": 0,
            "defer": 0,
            "board": self.timing.search_seconds,
            "feedback": self.timing.search_seconds,
            "guide": self.timing.search_seconds,
            "read": 1,
            "reply": 1,
            "wait": 1,
            "read_code": self.timing.read_seconds_per_100_lines,
            "search": self.timing.search_seconds,
            "diff": self.timing.search_seconds,
            "edit": self.timing.edit_seconds_per_100_lines,
            "command": self.timing.command_seconds,
            "test": self.timing.command_seconds,
            "handoff": self.timing.handoff_seconds,
            "apply_handoff": self.timing.handoff_seconds,
            "decline_handoff": 0,
            "submit": self.timing.submit_seconds,
            "invite": self.timing.invite_seconds,
            "invite_here": self.timing.invite_seconds,
        }[tool]

    def activity_context(self, who, active, menu):
        if active is None:
            return []
        remaining = self.remaining(who)
        context = [
            f"You are participating in {active.kind} {active.id}. "
            f"Latest end: {clock(active.members[who].end)}; "
            f"remaining usable time: {remaining} seconds.",
            "Tool costs in seconds: " + json.dumps(menu.get("costs", {})),
        ]
        if menu.get("blocked"):
            context.append("Too little time for: " + json.dumps(menu["blocked"]))
        if isinstance(active, ConversationActivity):
            context.append(f"Topic: {active.topic}. Unread messages: {len(active.unread(who))}.")
        return context

    def observation(self, who):
        active = self.activities.get(self.current.get(who))
        place = self.env.world.locations[who]
        menu = self.menu(who)
        layer = "tool" if active else "selection"
        context = [
            self.current_facts(who),
            "People here: "
            + ", ".join(
                p
                for p in self.env.world.occupants(place)
                if (p in self.outside) == (who in self.outside)
            )
            + ".",
            self.activity_contract(who),
        ]
        if not active and who in self.selection_feedback:
            context.append("Recent feedback: " + self.selection_feedback[who])
        if who in self.outside:
            opening = self.next_opening(place)
            context.append(
                "You are waiting outside the closed venue. "
                + (f"It opens at {clock(opening)}." if opening else "It will not reopen today.")
            )
        context += self.daily_context(who)
        context += self.activity_context(who, active, menu)
        if active:
            context += active.feedback.get(who, [])[-4:]
            if isinstance(active, WorkActivity):
                context.append(
                    f"Job: {active.task_id or 'none assigned'}. "
                    f"Work mode: {active.mode}. Relay owner: {active.relay_owner}. "
                    "Your repository is private; partners exchange code handoffs."
                )
        context += [self.env.board_view(who), self.env.status_view(who, include_evidence=False)]
        invitations = self.invitation_views(who)
        if invitations:
            context.append("Your invitations/appointments: " + json.dumps(invitations))
        conversations = [
            {"id": a.id, "topic": a.topic, "participants": list(a.participants)}
            for a in self.activities.values()
            if isinstance(a, ConversationActivity) and self.conversation_access(who, a)
        ]
        if conversations:
            context.append("Open conversations here: " + json.dumps(conversations))
        if menu.get("work"):
            context.append("Available public/paused work: " + json.dumps(menu["work"]))
        situation = "\n".join(context)
        return Observation(
            agent=who,
            time=self.now // 60,
            place=place,
            scene=f"day-{day_of(self.now // 60):04d}/activities",
            situation=situation,
            setting=self.town_setting(),
            percepts=self.env.perceive(who),
            evidence=self.env.work_evidence(who),
            allowed=(MayActivity(layer=layer, menu=menu),),
            places=situations.place_names(self.env, who),
            decision_layer="activity_tool" if active else "choose_activity",
            correction_context=situation[:5000],
        )

    async def decisions(self, people):
        observations = [self.observation(who) for who in people]

        async def ask(who, observation):
            agent = self.sim.agents[who]
            method = agent.choose_tool if who in self.current else agent.choose_activity
            try:
                return await method(observation)
            except StructuredOutputError as error:
                return error

        replies = await asyncio.gather(
            *(ask(who, o) for who, o in zip(people, observations, strict=True))
        )
        for who, reply in zip(people, replies, strict=True):
            if isinstance(reply, StructuredOutputError):
                lapse(self.env, who, reply, time=self.now // 60)
                if who in self.current:
                    self.leave(who, "No valid decision could be obtained.")
                self.start_rest(who, self.end)
                continue
            key = (self.now, who)
            self.transitions[key] = self.transitions.get(key, 0) + 1
            if self.transitions[key] > self.timing.max_zero_transitions:
                raise ActivityLoopError(
                    f"{who} repeatedly changed activities without advancing time"
                )
            self.emit(
                EventKind.DECISION,
                f"{who} chose {reply.action.kind}.",
                actor=who,
                thought=reply.thought,
                action=reply.action.model_dump(mode="json"),
                layer="activity_tool" if who in self.current else "choose_activity",
            )
            try:
                if not isinstance(reply.action, Choice):
                    raise Rejected("Choose an activity or one of its tools, as shown.")
                self.schedule(who, reply.action)
            except (Rejected, ValueError, KeyError) as error:
                self.reject(who, reply.action, str(error))

    def reject(self, who, action, reason):
        if who not in self.current:
            self.selection_feedback[who] = str(reason)
        self.env._reject(
            who,
            action.model_dump(mode="json"),
            Rejected(reason),
            time=self.now // 60,
            place=self.env.world.locations[who],
            scene="activities",
        )

    def enter(self, activity, who, until):
        if who in self.current:
            raise Rejected("Leave the current activity before joining another.")
        until = min(until, self.end)
        if not isinstance(activity, MoveActivity) and not (
            isinstance(activity, ConversationActivity) and activity.outside
        ):
            until = min(until, self.activity_closes(activity))
        if until <= self.now:
            raise Rejected("There is no time left for this activity.")
        cursor = len(activity.messages) if isinstance(activity, ConversationActivity) else 0
        activity.members[who] = Member(
            start=self.now,
            end=until,
            cursor=cursor,
            joined_cursor=cursor,
            event_cursor=self.env.log.count,
        )
        activity.status = "active"
        if isinstance(activity, ConversationActivity) and len(activity.participants) >= 2:
            activity.had_company = True
        self.selection_feedback.pop(who, None)
        activity.latest_end = max(activity.latest_end, until)
        self.activities[activity.id] = activity
        self.current[who] = activity.id
        self.queue.add(until, "member_end", priority=2, who=who, activity=activity.id, until=until)
        self.emit(
            EventKind.ACTIVITY_ENTERED,
            f"{who} started {activity.kind} at {clock(self.now)}.",
            actor=who,
            activity=activity.id,
            activity_type=activity.kind,
            start=self.now / 60,
            end=until / 60,
            participants=list(activity.participants),
            outside=who in self.outside,
        )

    def leave(self, who, reason):
        ident = self.current.pop(who, None)
        if ident is None:
            return
        activity = self.activities[ident]
        # The nightly boundary ends membership, not a still-future waking time.
        # Every earlier interruption (including venue closure or invitations) cancels it.
        if isinstance(activity, RestActivity) and self.now < self.end:
            self.rest_intents.pop(who, None)
        member = activity.members[who]
        member.active = False
        if pending := self.pending.pop(who, None):
            self.emit(
                EventKind.TOOL_CANCELLED,
                "The activity ended before this operation completed.",
                actor=who,
                activity=ident,
                tool=pending.action.tool,
            )
        recent = [text[:400] for text in activity.feedback.get(who, [])[-3:]]
        progress = (
            f" Job {activity.task_id} and its private workspace are preserved."
            if isinstance(activity, WorkActivity)
            else ""
        )
        summary = f"{activity.kind} {ident}: {reason} " + " ".join(recent) + progress
        activity.result[who] = summary
        if not activity.participants:
            activity.status = "paused" if isinstance(activity, WorkActivity) else "ended"
        self.emit(
            EventKind.ACTIVITY_LEFT,
            summary,
            actor=who,
            activity=ident,
            activity_type=activity.kind,
            reason=reason,
            result=summary,
            start=member.start / 60,
            end=self.now / 60,
        )
        if (
            isinstance(activity, ConversationActivity)
            and len(activity.participants) < 2
            and (not activity.spontaneous or activity.had_company)
        ):
            activity.status = "ended"
            for other in list(activity.participants):
                self.leave(other, "Fewer than two people remain in the conversation.")
        self.finish_rest_transition(who)
        if who in self.deferred_invitation_replies:
            self.deliver_invitation_replies(who)

    def start_rest(self, who, until, *, wake=True, waiting_for=None):
        """Reuse one resident's idle activity; each entry is a fresh membership."""
        if who in self.current:
            raise Rejected("Leave the current activity before joining another.")
        if min(until, self.end, self.close_at(self.env.world.locations[who])) <= self.now:
            raise Rejected("There is no time left for this activity.")
        ident = self.rest_activities.get(who)
        activity = self.activities.get(ident)
        if activity is None:
            activity = RestActivity(
                id=self.identifier("rest"),
                place=self.env.world.locations[who],
                start=self.now,
                latest_end=until,
            )
            self.rest_activities[who] = activity.id
        else:
            activity.place = self.env.world.locations[who]
            activity.start = self.now
            activity.latest_end = until
            activity.members = {}
            activity.feedback = {}
            activity.result = {}
        activity.wake_invitations = wake
        activity.waiting_for = waiting_for
        self.enter(activity, who, until)
        if until > self.end:
            self.rest_intents[who] = {"until": until, "wake": wake}

    def finish_rest_transition(self, who):
        request = self.rest_requests.pop(who, None)
        if request is None:
            return
        if request["until"] <= self.now:
            self.feedback(who, "The chosen rest ending time has passed; choose a new activity.")
            return
        if self.now >= self.end:
            # A started speech may finish after closing. Preserve the wake deadline
            # without logging an activity that cannot enter until the next morning.
            self.rest_intents[who] = {"until": request["until"], "wake": request["wake"]}
            return
        self.start_rest(who, **request)

    def schedule(self, who, action):
        if who in self.pending:
            raise Rejected("Finish your current tool first.")
        if action.operation == "activity_tool" and action.tool == "help":
            return self.show_help(who)
        if who not in self.current or action.operation == "select_rest":
            return self.select(who, action)
        if action.operation != "activity_tool":
            raise Rejected("Choose a tool or leave your current activity first.")
        if action.tool not in self.menu(who)["tools"]:
            raise Rejected("That tool is unavailable here or exceeds the remaining time.")
        prepared, cost = self.prepare(who, action)
        if cost > self.remaining(who):
            raise Rejected(
                f"This operation needs {cost} seconds, but only {self.remaining(who)} remain."
            )
        pending = PendingTool(self.current[who], action, self.now, self.now + cost, prepared)
        pending.token = self.identifier("tool")
        self.pending[who] = pending
        self.queue.add(
            pending.end,
            "tool",
            priority=0,
            who=who,
            start=pending.start,
            activity=pending.activity,
            token=pending.token,
        )
        self.emit(
            EventKind.TOOL_STARTED,
            f"{who} began {action.tool}; finishes {clock(pending.end)}.",
            actor=who,
            activity=pending.activity,
            tool=action.tool,
            arguments=action.arguments,
            start=self.now / 60,
            end=pending.end / 60,
            cost_seconds=cost,
        )

    def select(self, who, action):
        if action.operation == "activity_tool" and action.tool == "help":
            return self.show_help(who)
        place = self.env.world.locations[who]
        if who in self.outside and action.operation in (
            "select_work",
            "resume_work",
        ):
            raise Rejected(
                "You are outside the closed venue; "
                "wait for opening before entering an indoor activity."
            )
        if action.operation == "select_rest":
            day = action.arguments.get("day", "today")
            if day not in ("today", "tomorrow"):
                raise Rejected("Choose today or tomorrow for the rest ending time.")
            waiting_for = action.arguments.get("invitation")
            if waiting_for:
                if waiting_for not in self.menu(who)["ready_invitations"]:
                    raise Rejected(
                        "Confirm and arrive at this pending meeting before waiting for it."
                    )
                until = min(self.end, self.invitations[waiting_for].grace_end)
            else:
                until = at(
                    day_of(self.now // 60) + int(day == "tomorrow"), action.arguments["until"]
                )
            if until <= self.now:
                raise Rejected(
                    f"Rest not started: requested day {day_of(until // 60)} "
                    f"{clock(until)}; now day {day_of(self.now // 60)} {clock(self.now)}. "
                    "Choose a future ending time today or tomorrow."
                )
            if self.now >= self.end:
                raise Rejected("The day has closed.")
            active = self.activities.get(self.current.get(who))
            if active is not None and not isinstance(active, WorkActivity | ConversationActivity):
                raise Rejected("Finish your current activity before choosing rest.")
            if min(until, self.end, self.close_at(place)) <= self.now:
                raise Rejected("There is no time left for this activity.")
            request = {
                "until": until,
                "wake": action.arguments.get("wake", True),
                "waiting_for": waiting_for,
            }
            if active is None:
                self.start_rest(who, **request)
            else:
                self.rest_requests[who] = request
                self.leave(who, "Switched to rest.")
        elif action.operation == "select_move":
            if action.target not in self.menu(who)["moves"].values():
                raise Rejected(
                    "That destination is unavailable or cannot be reached before the day ends."
                )
            until = self.now + self.travel_seconds(place, action.target)
            activity = MoveActivity(
                id=self.identifier("move"),
                place=place,
                start=self.now,
                latest_end=until,
                origin=place,
                destination=action.target,
            )
            self.enter(activity, who, until)
            self.queue.add(until, "arrival", priority=0, who=who, activity=activity.id)
        elif action.operation in ("select_work", "resume_work"):
            if action.operation == "resume_work":
                activity = self.activities[action.target]
                if (
                    not isinstance(activity, WorkActivity)
                    or activity.status == "ended"
                    or not self.work_access(who, activity)
                ):
                    raise Rejected("You cannot resume that work here.")
                claim = self.env.board.claim_of(who)
                if activity.task_id and (claim is None or activity.task_id != claim.task.id):
                    raise Rejected("You no longer hold this work's job.")
                if activity.place != place:
                    if activity.participants:
                        raise Rejected(
                            "Go to this active work's location before joining its participants."
                        )
                    # No one is using this session. Its job, workspace keys, handoffs and
                    # notes survive; historical locations remain in the immutable log.
                    activity.place = place
            else:
                claim = self.env.board.claim_of(who)
                candidates = [
                    a
                    for a in self.activities.values()
                    if isinstance(a, WorkActivity)
                    and a.public
                    and a.status != "ended"
                    and claim
                    and a.task_id == claim.task.id
                    and a.place == place
                    and self.work_access(who, a)
                ]
                # Prefer a live collaboration here, then one's own vacant local session.
                # An old activity elsewhere never locks where a resident may start work.
                shared = next(
                    (
                        a
                        for a in candidates
                        if a.status == "active" and any(p != who for p in a.participants)
                    ),
                    None,
                )
                shared = shared or next(
                    (a for a in candidates if not a.participants and who in a.members), None
                )
                if shared:
                    self.enter(shared, who, self.now + action.seconds)
                    return
                activity = WorkActivity(
                    id=self.identifier("work"),
                    place=place,
                    start=self.now,
                    latest_end=self.now + action.seconds,
                    public=action.arguments.get("public", False),
                    mode=action.arguments.get("mode", "parallel"),
                    relay_owner=who,
                )
                claim = self.env.board.claim_of(who)
                activity.task_id = claim.task.id if claim else None
            self.enter(activity, who, self.now + action.seconds)
        elif action.operation == "start_chat":
            if not self.menu(who)["nearby_people"]:
                raise Rejected("Nobody is within earshot here. Move somewhere with people first.")
            outside = who in self.outside
            if not outside and not self.venue_open(place):
                raise Rejected("This indoor venue is closed.")
            activity = ConversationActivity(
                id=self.identifier("conversation"),
                place=place,
                start=self.now,
                latest_end=self.end if outside else self.close_at(place),
                topic=action.topic,
                public=True,
                spontaneous=True,
                outside=outside,
            )
            self.enter(activity, who, activity.latest_end)
            self.emit(
                EventKind.DISCUSSION,
                f"{who} opened a local conversation: {activity.topic}. "
                "Join freely or continue your activity.",
                actor=who,
                audience=list(self.conversation_audience(activity)),
                activity=activity.id,
                participants=list(activity.participants),
                public_conversation=True,
                conversation_started=True,
                outside=outside,
            )
        elif action.operation == "select_conversation":
            activity = self.activities.get(action.target)
            if not isinstance(activity, ConversationActivity) or not self.conversation_access(
                who, activity
            ):
                raise Rejected("That conversation is not open to you here.")
            self.enter(
                activity,
                who,
                min(self.now + (action.seconds or self.end - self.now), activity.latest_end),
            )
            for other in activity.participants:
                if other != who:
                    self.sim._met[who].add(other)
                    self.sim._met[other].add(who)
        elif action.operation == "activity_tool" and action.tool in (
            "invite",
            "accept",
            "decline",
            "defer",
        ):
            # Free residents may arrange/confirm conversations without reserving anybody.
            self.invitation_action(who, action.tool, action.arguments)
        else:
            raise Rejected("Choose rest, movement, work, or an available conversation.")

    def prepare(self, who, action):
        tool, args = action.tool, action.arguments
        activity = self.activities[self.current[who]]
        data = {}
        cost = self.minimum_cost(tool)
        if tool == "read":
            messages = activity.unread(who)
            data["messages"] = [m.model_dump() for m in messages]
            cost = self.timing.text_cost("\n".join(m.text for m in messages), reading=True)
        elif tool == "reply":
            if not isinstance(activity, ConversationActivity):
                raise Rejected("Reply within a conversation.")
            if not args.get("text") or units(args["text"]) > self.timing.max_message_units:
                raise Rejected("Keep this reply within the message size limit.")
            cost = self.timing.text_cost(args["text"])
        elif tool == "wait":
            if not isinstance(activity, ConversationActivity):
                raise Rejected("Wait for messages within a conversation.")
            cost = min(max(1, int(args["seconds"])), self.remaining(who))
            if activity.unread(who):
                cost = 0
        elif tool == "read_code":
            lines = int(args["lines"])
            if not 1 <= lines <= self.timing.max_read_lines or int(args["line"]) < 1:
                raise Rejected("Choose a bounded line window.")
            cost = math.ceil(lines / 100) * self.timing.read_seconds_per_100_lines
        elif tool == "edit":
            patch = args["patch"]
            if len(patch.encode()) > 16000:
                raise Rejected("Apply a smaller patch.")
            cost = (
                max(1, math.ceil(len(patch.splitlines()) / 100))
                * self.timing.edit_seconds_per_100_lines
            )
        if tool in ("read_code", "search"):
            path = str(args["path"])
            if path.startswith("/") or ".." in path.split("/"):
                raise Rejected("Use a path inside the repository.")
        if tool in ("handoff", "apply_handoff", "decline_handoff"):
            claim = self.env.board.claim_of(who)
            if not claim:
                raise Rejected("You have no job to hand over.")
            if tool == "handoff" and args["to"] not in claim.workers:
                raise Rejected("Only hand work to a partner on this job.")
            if tool != "handoff":
                h = self.handoffs[args["handoff"]]
                if h.recipient != who or h.task_id != claim.task.id or h.status != "offered":
                    raise Rejected("That code handoff is not available to you.")
        return data, cost

    def invitation_action(self, who, tool, args):
        reply_owner = None
        if tool == "invite_here":
            activity = self.activities[self.current[who]]
            people = tuple(dict.fromkeys(args["people"]))
            if not people or any(
                p not in self.env.agents or p in activity.participants for p in people
            ):
                raise Rejected("Invite residents who are not already in this conversation.")
            invitation = Invitation(
                id=self.identifier("invitation"),
                owner=who,
                invited=people,
                confirmed=[],
                place=activity.place,
                topic=activity.topic,
                start=self.now,
                duration=activity.latest_end - self.now,
                grace_end=activity.latest_end,
                conversation=activity.id,
            )
            self.invitations[invitation.id] = invitation
            self.queue.add(
                invitation.grace_end, "invitation_expired", priority=3, invitation=invitation.id
            )
        elif tool in ("accept", "decline", "defer"):
            invitation = self.invitations.get(args.get("invitation"))
            if (
                invitation is None
                or invitation.status != "pending"
                or who not in invitation.invited
                or who in invitation.declined
                or self.now > invitation.grace_end
            ):
                raise Rejected("That invitation is no longer available.")
            reply_owner = invitation.owner if invitation.owner != who else None
            if tool == "accept":
                if who in invitation.confirmed:
                    return  # Replayed/stale accepts do not emit another invitation notification.
                invitation.confirmed.append(who)
            elif tool == "decline":
                invitation.declined.append(who)
                invitation.confirmed = [p for p in invitation.confirmed if p != who]
                if all(p in invitation.declined for p in invitation.invited):
                    invitation.status = "cancelled"
            else:
                if invitation.conversation:
                    raise Rejected(
                        "An ongoing conversation cannot be rescheduled; leave or arrange a new one."
                    )
                start = at(day_of(self.now // 60), args["at"])
                if start <= max(self.now, invitation.start) or start >= self.end:
                    raise Rejected("Propose a later time today, before day end.")
                if not self.venue_open(invitation.place, start):
                    raise Rejected("That meeting place will be closed at the proposed time.")
                old = invitation
                others = tuple(
                    p for p in (old.owner, *old.invited) if p != who and p not in old.declined
                )
                invitation = Invitation(
                    id=self.identifier("invitation"),
                    owner=who,
                    invited=others,
                    confirmed=[who],
                    place=old.place,
                    topic=old.topic,
                    start=start,
                    duration=old.duration,
                    grace_end=min(self.end, start + self.timing.appointment_grace_seconds),
                    public=old.public,
                    supersedes=old.id,
                )
                old.status = "cancelled"
                old.superseded_by = invitation.id
                self.invitations[invitation.id] = invitation
                self.queue.add(start, "appointment", invitation=invitation.id)
                self.queue.add(
                    invitation.grace_end, "invitation_expired", priority=3, invitation=invitation.id
                )
        else:
            people = tuple(dict.fromkeys(args["people"]))
            if not people or who in people or any(p not in self.env.agents for p in people):
                raise Rejected("Invite other residents by name.")
            places = self.menu(who)["places"]
            if args["place"] not in places:
                raise Rejected("That meeting place is unavailable.")
            place = places[args["place"]]
            start = at(day_of(self.now // 60), args["at"]) if args.get("at") else self.now
            if start < self.now or start >= self.end:
                raise Rejected(
                    f"Invitation not sent: requested day {day_of(start // 60)} "
                    f"{clock(start)}; now day {day_of(self.now // 60)} {clock(self.now)}. "
                    "Choose another time today before day end, or use null for now."
                )
            if not self.venue_open(place, start):
                raise Rejected("That meeting place will be closed.")
            duplicate = next(
                (
                    i
                    for i in self.invitations.values()
                    if i.status == "pending"
                    and self.now <= i.grace_end
                    and i.owner == who
                    and set(i.invited) == set(people)
                    and i.place == place
                    and i.topic.strip().casefold() == args["topic"].strip().casefold()
                    and (i.start == start or (not args.get("at") and i.start <= self.now))
                    and i.public == args.get("public", False)
                ),
                None,
            )
            if duplicate:
                self.feedback(
                    who,
                    f"Invitation {duplicate.id} already covers this conversation; "
                    "check its confirmation/readiness instead of sending another.",
                )
                return {"invitation": duplicate.id, "created": False}
            scheduled = bool(args.get("at"))
            grace = (
                min(self.end, start + self.timing.appointment_grace_seconds)
                if scheduled
                else self.end
            )
            invitation = Invitation(
                id=self.identifier("invitation"),
                owner=who,
                invited=people,
                confirmed=[who],
                place=place,
                topic=args["topic"],
                start=start,
                duration=int(args["minutes"]) * 60,
                grace_end=grace,
                public=args.get("public", False),
            )
            self.invitations[invitation.id] = invitation
            self.queue.add(start, "appointment", invitation=invitation.id)
            self.queue.add(grace, "invitation_expired", priority=3, invitation=invitation.id)
        if self.sim.config.lunch_place:
            for person in invitation.confirmed:
                departure = invitation.start - self.travel_seconds(
                    self.env.world.locations[person], invitation.place
                )
                self.queue.add(max(self.now, departure), "daily_choice")
        audience = [invitation.owner, *invitation.invited]
        owner_activity = self.activities.get(self.current.get(reply_owner))
        delayed = owner_activity is not None and not isinstance(owner_activity, RestActivity)
        if delayed:
            audience = [person for person in audience if person != reply_owner]
        event = self.emit(
            EventKind.DISCUSSION,
            f"{who} {tool}: {invitation.topic}, at {clock(invitation.start)}; "
            f"confirmed: {', '.join(invitation.confirmed)}. Nobody is reserved.",
            actor=who,
            audience=audience,
            invitation=invitation.id,
            place_id=invitation.place,
            start_seconds=invitation.start,
            grace_seconds=invitation.grace_end,
            response=tool,
            declined=list(invitation.declined),
            supersedes=invitation.supersedes,
        )
        if delayed:
            self.deferred_invitation_replies.setdefault(reply_owner, []).append(
                {
                    "source_event_id": event.seq,
                    "actor": who,
                    "text": event.text,
                    "payload": {
                        key: value for key, value in event.payload.items() if key != "sim_seconds"
                    },
                }
            )
        return {"invitation": invitation.id, "created": tool in ("invite", "invite_here", "defer")}

    def start_ready_conversations(self):
        for invitation in self.invitations.values():
            if (
                invitation.status != "pending"
                or not invitation.start <= self.now <= invitation.grace_end
            ):
                continue
            people = [
                p
                for p in invitation.confirmed
                if self.ready_for_invitation(p, invitation)
                and p not in self.outside
                and self.env.world.locations[p] == invitation.place
            ]
            if invitation.conversation:
                activity = self.activities[invitation.conversation]
                if activity.status != "active" or len(activity.participants) < 2:
                    invitation.status = "cancelled"
                    continue
                for who in people:
                    if who in self.current:
                        self.leave(who, "A confirmed conversation is ready.")
                    activity.invited = tuple(dict.fromkeys((*activity.invited, who)))
                    self.enter(activity, who, activity.latest_end)
                    for other in activity.participants:
                        self.sim._met[who].update([other] if other != who else [])
                        self.sim._met[other].update([who] if other != who else [])
                if all(
                    p in activity.members or p in invitation.declined for p in invitation.invited
                ):
                    invitation.status = "started"
                continue
            if len(people) < 2 or not self.venue_open(invitation.place):
                continue
            until = min(self.now + invitation.duration, self.close_at(invitation.place))
            if until <= self.now:
                continue
            for who in people:
                if who in self.current:
                    self.leave(
                        who, "A confirmed conversation is ready; invitations may wake this rest."
                    )
            activity = ConversationActivity(
                id=self.identifier("conversation"),
                place=invitation.place,
                start=self.now,
                latest_end=until,
                topic=invitation.topic,
                public=invitation.public,
                invited=(invitation.owner, *invitation.invited),
            )
            for who in people:
                self.enter(activity, who, until)
                self.sim._met[who].update(p for p in people if p != who)
            invitation.status, invitation.conversation = "started", activity.id
            self.emit(
                EventKind.DISCUSSION,
                f"Conversation began: {activity.topic}.",
                actor=invitation.owner,
                audience=people,
                activity=activity.id,
                participants=people,
                end_seconds=until,
                conversation_started=True,
            )

    def wake_rests(self):
        for who, ident in list(self.current.items()):
            activity = self.activities[ident]
            if not isinstance(activity, RestActivity) or not activity.wake_invitations:
                continue
            member = activity.members[who]
            if any(
                e.seq >= member.event_cursor and e.payload.get("public_conversation")
                for e in self.env.log.pending_events(who)
            ):
                self.leave(who, "A nearby public conversation opened; choose whether to join.")
                continue
            if activity.waiting_for:
                invitation = self.invitations.get(activity.waiting_for)
                if any(
                    e.seq >= member.event_cursor
                    and e.kind == EventKind.DISCUSSION
                    and e.payload.get("response") in ("accept", "decline", "defer")
                    and activity.waiting_for
                    in (e.payload.get("invitation"), e.payload.get("supersedes"))
                    for e in self.env.log.pending_events(who)
                ):
                    self.leave(who, "A reply arrived for the conversation you are waiting for.")
                    continue
                if not invitation or invitation.status == "cancelled":
                    self.leave(who, "The conversation you were waiting for was cancelled.")
                continue
            member = activity.members[who]
            events = self.env.log.pending_events(who)
            if any(
                e.seq >= member.event_cursor
                and e.kind in (EventKind.DISCUSSION, EventKind.TASK_PROPOSED)
                for e in events
            ):
                self.leave(who, "A new invitation arrived.")
            member.event_cursor = self.env.log.count

    async def complete_tool(self, who, pending, *, record_completion=True):
        if self.current.get(who) != pending.activity:
            return
        activity = self.activities[pending.activity]
        action, args = pending.action, pending.action.arguments
        tool = action.tool
        outcome = {}
        try:
            if tool == "leave":
                self.leave(who, "Paused or left voluntarily.")
            elif tool in ("invite", "invite_here", "accept", "decline", "defer"):
                outcome = {"success": True, **(self.invitation_action(who, tool, args) or {})}
            elif tool == "board":
                self.feedback(who, self.env.board_view(who))
            elif tool == "feedback":
                self.feedback(who, self.env.status_view(who))
            elif tool == "guide":
                claim = self.env.board.claim_of(who)
                if claim is None:
                    raise Rejected("Claim a job before reading its repository work guide.")
                provider = self.env.providers[claim.task.trade]
                self.feedback(who, provider.work_guide(claim.task.parts[0]))
            elif tool == "claim":
                claim = ClaimTask(task_id=args["job"], partner=args.get("partner"))
                await self.env.execute(
                    who,
                    claim,
                    time=self.now // 60,
                    scene="activities",
                    witnesses=self.env.world.occupants(activity.place),
                )
                current = self.env.board.claim_of(who)
                if current:
                    activity.task_id = current.task.id
            elif tool == "read":
                messages = pending.prepared["messages"]
                if messages:
                    activity.members[who].cursor = max(m["id"] for m in messages) + 1
                text = "\n".join(
                    f"{clock(m['sent_at'])} {m['author']}: {m['text']}" for m in messages
                )
                self.emit(
                    EventKind.CONVERSATION_READ,
                    text or "No unread messages.",
                    actor=who,
                    activity=activity.id,
                    message_ids=[m["id"] for m in messages],
                )
                activity.feedback[who] = [text or "No unread messages."]
            elif tool == "reply":
                message = Message(
                    id=len(activity.messages),
                    author=who,
                    sent_at=self.now,
                    text=args["text"],
                    audience=self.conversation_audience(activity),
                )
                activity.messages.append(message)
                # Only a read tool reveals the text; research logs retain its full payload.
                self.emit(
                    EventKind.CONVERSATION_MESSAGE,
                    f'{who} says: "{args["text"]}"'
                    if activity.spontaneous
                    else f"{who} posted a new message.",
                    actor=who,
                    audience=list(message.audience),
                    activity=activity.id,
                    message=message.model_dump(mode="json"),
                )
                for other in list(activity.participants):
                    self.sim._met[who].update([other] if other != who else [])
                    waiting = self.pending.get(other)
                    if waiting and waiting.action.tool == "wait":
                        del self.pending[other]
                        self.feedback(other, "A new message is ready to read.")
                        self.emit(
                            EventKind.TOOL_COMPLETED,
                            "Waiting ended on a new message.",
                            actor=other,
                            activity=activity.id,
                            tool="wait",
                            start=waiting.start / 60,
                            end=self.now / 60,
                        )
            elif tool == "wait":
                self.feedback(
                    who,
                    "Messages are ready to read."
                    if activity.unread(who)
                    else "The wait ended without a new message.",
                )
            elif tool == "submit":
                await self.submit(who, args["report"])
            elif tool in ("handoff", "apply_handoff", "decline_handoff"):
                await self.handoff_tool(who, tool, args, activity)
            else:
                claim = self.env.board.claim_of(who)
                if claim is None or claim.task.id != activity.task_id:
                    raise Rejected("You no longer hold this job.")
                command = self.command_for(tool, args)
                emitted = await self.env.execute(
                    who,
                    RunCommand(task_id=claim.task.id, command=command),
                    time=self.now // 60,
                    scene="activities",
                    witnesses=[who],
                )
                activity.feedback[who] = [e.text[-16000:] for e in emitted]
                activity.history.append(
                    {
                        "time": self.now,
                        "worker": who,
                        "tool": tool,
                        "feedback": activity.feedback[who],
                    }
                )
        except (Rejected, ValueError, KeyError) as error:
            outcome = {"success": False, "error": str(error)}
            self.reject(who, action, str(error))
            self.feedback(who, str(error))
        finally:
            if record_completion:
                self.record_tool_completion(who, pending, tool, args, activity, outcome)
        return outcome

    def record_tool_completion(self, who, pending, tool, args, activity, outcome):
        self.emit(
            EventKind.TOOL_COMPLETED,
            f"{who} {'failed' if outcome.get('success') is False else 'ended'} {tool}.",
            actor=who,
            activity=activity.id,
            tool=tool,
            start=pending.start / 60,
            end=self.now / 60,
            arguments=args,
            **outcome,
        )

    def command_for(self, tool, args):
        if tool in ("command", "test"):
            return args["command"]
        if tool == "diff":
            return "git diff --stat && git diff -- ."
        if tool in ("read_code", "search"):
            # Resolve symlinks in the container too; typed tools never read outside /testbed.
            check = "import os; p=os.path.realpath(" + repr(args["path"]) + "); "
            check += "assert os.path.commonpath(['/testbed',p])=='/testbed'; "
            if tool == "read_code":
                check += (
                    "import itertools; f=open(p,encoding='utf-8',errors='replace'); "
                    f"print(''.join(itertools.islice(f,{int(args['line']) - 1},"
                    f"{int(args['line']) - 1 + int(args['lines'])})))"
                )
                return "python -c " + shlex.quote(check)
            script = check + "\ncount=0\n"
            script += (
                "paths=[p] if os.path.isfile(p) else "
                "(os.path.join(d,n) for d,_,ns in os.walk(p) "
                "if '/.git' not in d for n in ns)\n"
            )
            script += (
                "for name in paths:\n"
                " if os.path.commonpath(['/testbed',os.path.realpath(name)])"
                "!='/testbed': continue\n try:\n"
                "  with open(name,encoding='utf-8',errors='replace') as f:\n"
                "   for i,line in enumerate(f,1):\n    if "
                + repr(args["pattern"])
                + " in line:\n     print('%s:%d:%s'%(name,i,line.rstrip())); count+=1\n"
                "     if count>=200: raise SystemExit(0)\n"
                " except (OSError,UnicodeError): pass\n"
            )
            return "python -c " + shlex.quote(script)
        if tool == "edit":
            # Pass the patch through a file, not through an agent-controlled shell here-doc.
            script = (
                "import subprocess,tempfile; p=" + repr(args["patch"]) + "; "
                "f=tempfile.NamedTemporaryFile(); f.write(p.encode()); f.flush(); "
                "subprocess.check_call(['git','apply','--check',f.name]); "
                "subprocess.check_call(['git','apply',f.name])"
            )
            return "python -c " + shlex.quote(script)
        raise Rejected("Unknown repository operation.")

    async def handoff_tool(self, who, tool, args, activity):
        claim = self.env.board.claim_of(who)
        activity = self.relay_session(claim.task.id) or activity
        provider = self.env.providers[claim.task.trade]
        part = claim.task.parts[0]
        if tool == "handoff":
            patch = await provider.export_handoff(part, who, claim.task.id)
            handoff = Handoff(
                id=self.identifier("handoff"),
                task_id=claim.task.id,
                sender=who,
                recipient=args["to"],
                patch=patch,
                description=args["description"],
                created_at=self.now,
                version=hashlib.sha256(patch.encode()).hexdigest(),
            )
            self.handoffs[handoff.id] = handoff
            if activity.mode == "relay" and activity.relay_owner == who:
                activity.relay_owner = None
            self.emit(
                EventKind.CODE_HANDOFF,
                f"{who} offered code {handoff.version[:12]}: {handoff.description}",
                actor=who,
                audience=[who, handoff.recipient],
                task_id=claim.task.id,
                handoff=handoff.id,
                version=handoff.version,
                patch=patch,
            )
        else:
            handoff = self.handoffs[args["handoff"]]
            if (
                handoff.status != "offered"
                or handoff.recipient != who
                or handoff.task_id != claim.task.id
            ):
                raise Rejected("This handoff is not available.")
            if tool == "decline_handoff":
                handoff.status = "declined"
                if activity.mode == "relay":
                    activity.relay_owner = handoff.sender
                self.feedback(who, "The code handoff was declined; your workspace did not change.")
                return
            result = await provider.apply_handoff(part, who, claim.task.id, handoff.patch)
            if result["exit_code"]:
                self.feedback(
                    who,
                    "Handoff conflict: your previous workspace was preserved.\n" + result["output"],
                )
                return
            handoff.status = "accepted"
            if activity.mode == "relay":
                activity.relay_owner = who
            self.emit(
                EventKind.CODE_HANDOFF,
                f"{who} applied code handoff {handoff.id}.",
                actor=who,
                audience=[handoff.sender, who],
                task_id=claim.task.id,
                handoff=handoff.id,
                version=handoff.version,
                applied=True,
            )

    async def submit(self, who, report):
        claim = self.env.board.claim_of(who)
        if claim is None or claim.task.id in self.assessments:
            raise Rejected("There is no unsubmitted job to send for assessment.")
        provider = self.env.providers[claim.task.trade]
        patch = await provider.prepare_submission(
            claim.task.parts[0], who, claim.task.id, "WORKTREE"
        )
        action = SubmitWork(task_id=claim.task.id, solution=patch, report=report)
        due = self.now + self.timing.assessment_seconds
        self.assessments[claim.task.id] = {
            "due": due,
            "agent": who,
            "action": action.model_dump(mode="json"),
            "place": self.env.world.locations[who],
            "delayed": False,
        }
        self.start_assessment(claim.task.id)
        self.queue.add(due, "assessment", job=claim.task.id)
        self.emit(
            EventKind.SUBMISSION_PENDING,
            "Repair submitted. " + self.assessment_waiting(who).strip(),
            actor=who,
            audience=list(claim.workers),
            task_id=claim.task.id,
            due_seconds=due,
        )
        self.leave(who, "Repair submitted for background assessment.")

    def start_assessment(self, job):
        if job in self.futures:
            return
        entry = self.assessments[job]
        if self.now < entry.get("retry_at", 0):
            return
        claim = self.env.board.claims.get(job)
        if claim is None:
            return
        provider = self.env.providers[claim.task.trade]

        async def run():
            try:
                return await provider.assess(claim.task.parts[0], entry["action"]["solution"])
            except Exception as error:
                return AssessmentUnavailable(str(error))

        self.futures[job] = asyncio.create_task(run())
        entry.pop("retry_at", None)

    async def assessment(self, job):
        if job not in self.assessments:
            return
        entry = self.assessments[job]
        if self.now < entry.get("retry_at", 0):
            return
        if job not in self.env.board.claims:
            self.assessments.pop(job)
            future = self.futures.pop(job, None)
            if future:
                future.cancel()
                await asyncio.gather(future, return_exceptions=True)
            return
        future = self.futures.get(job)
        if future is None:
            self.start_assessment(job)
            future = self.futures.get(job)
            if future is None:
                return
        if not future.done():
            if not entry["delayed"]:
                entry["delayed"] = True
                claim = self.env.board.claims.get(job)
                self.emit(
                    EventKind.ACTIVITY_FEEDBACK,
                    "Assessment is delayed; this is not a failed repair.",
                    actor=entry["agent"],
                    audience=list(claim.workers) if claim else [entry["agent"]],
                    task_id=job,
                    assessment_delayed=True,
                )
            self.queue.add(self.now + 300, "assessment", job=job)
            return
        result = future.result()
        if isinstance(result, AssessmentUnavailable):
            claim = self.env.board.claims[job]
            day = day_of(self.now // 60)
            extra = int(claim.assessment_fault_day != day)
            self.env.board.claims[job] = claim.model_copy(
                update={
                    "grace_days": claim.grace_days + extra,
                    "assessment_fault_day": day,
                }
            )
            attempt = entry.get("retry_attempts", 0) + 1
            delay = min(
                self.timing.assessment_retry_seconds * 2 ** min(attempt - 1, 16),
                self.timing.assessment_retry_max_seconds,
            )
            entry.update(retry_attempts=attempt, retry_at=self.now + delay, delayed=True)
            del self.futures[job]
            self.queue.add(entry["retry_at"], "assessment", job=job)
            self.emit(
                EventKind.WORK_DELAYED,
                "The checking service is unavailable, not a failed repair. "
                "The clerk retains your submitted snapshot and will automatically retry at "
                f"{clock(entry['retry_at'])}.",
                actor=entry["agent"],
                audience=list(claim.workers),
                task_id=job,
                automatic_retry=True,
                retry_attempts=attempt,
                retry_at=entry["retry_at"],
                grace_days_added=extra,
            )
            return
        if job in self.env.board.claims:
            await self.env._submit(
                entry["agent"],
                SubmitWork.model_validate(entry["action"]),
                time=self.now // 60,
                place=entry["place"],
                scene="activities",
                prepared=(entry["action"]["solution"], result),
            )
        del self.assessments[job]
        del self.futures[job]

    def protect_assessment_deadlines(self, day):
        for job in self.assessments:
            claim = self.env.board.claims.get(job)
            if claim and claim.due_day < day:
                self.env.board.claims[job] = claim.model_copy(
                    update={"grace_days": claim.grace_days + day - claim.due_day}
                )

    def close_venue_for(self, who, place):
        """Close indoor access without choosing the resident's next destination."""
        if self.env.world.places[place].kind == PlaceKind.WORK:
            self.leave(who, "Code work closed; choose your next activity here or elsewhere.")
            self.outside.pop(who, None)
            self.feedback(
                who,
                "Code work is closed. You remain inside the workplace. "
                "You may chat, rest, or move elsewhere; everyone returns home at 22:00.",
            )
            return
        self.leave(who, "The place closed; choose your next activity outside.")
        self.outside[who] = place
        self.feedback(
            who,
            f"{self.env.world.places[place].name} is closed. You are outside its doors. "
            "Choose where to go, wait outside, or respond to invitations.",
            outside=True,
        )

    def daily_context(self, who):
        if not self.sim.config.lunch_place:
            return []
        day = day_of(self.now // 60)
        if at(day, "12:00") <= self.now < at(day, "14:00"):
            return [
                "Lunch is at "
                + self.sim.config.lunch_place
                + ". At the restaurant, rest while eating or start/join a conversation; "
                "named invitations are optional."
            ]
        if self.now >= at(day, "18:00"):
            venues = [p.name for p in self.env.world.places.values() if p.kind == PlaceKind.SOCIAL]
            examples = ", such as " + ", ".join(venues) if venues else ""
            return [
                "After work, you would enjoy spending part of the evening with neighbours. "
                "You can share work experience and ideas that may help with your tasks, "
                "or talk about everyday life and make friends. "
                "Good relationships can bring mutual support in future work and life. "
                f"Choose your own company and place{examples}."
            ]
        return []

    def daily_choices(self):
        """Finish started operations and travel before offering daily transitions."""
        if not self.sim.config.lunch_place or self.now >= self.end:
            return
        self.daily_waiting.clear()
        day = day_of(self.now // 60)
        state = self.daily_life.setdefault(str(day), {"lunched": [], "evening": [], "reminded": []})
        for who in self.sim.agents:
            if who in self.pending or who in getattr(self, "running", {}):
                continue
            activity = self.activities.get(self.current.get(who))
            if isinstance(activity, MoveActivity):
                continue
            if (
                not hasattr(self, "running")
                and isinstance(activity, ConversationActivity)
                and who not in state["lunched"]
                and self.now >= at(day, "12:00")
                and any(person in self.pending for person in activity.participants)
            ):
                self.daily_waiting.add(who)
                continue
            if self.now >= at(day, "12:00") and who not in state["lunched"]:
                destination = self.sim.config.lunch_place
                if self.env.world.locations[who] == destination:
                    state["lunched"].append(who)
                    self.feedback(
                        who, "You arrived for lunch. Rest while eating or converse freely."
                    )
                else:
                    self.leave(who, "Time for the daily lunch; work progress is preserved.")
                    if who in self.current:
                        continue
                    self.select(who, Choice(operation="select_move", target=destination))
                    continue
            if self.now >= at(day, "18:00") and who not in state["evening"]:
                state["evening"].append(who)
                if isinstance(
                    self.activities.get(self.current.get(who)), WorkActivity | RestActivity
                ):
                    self.leave(who, "Evening choices are available.")
                self.feedback(who, self.daily_context(who)[0])
            for invitation in self.invitations.values():
                key = invitation.id + ":" + who
                if (
                    invitation.status != "pending"
                    or who not in invitation.confirmed
                    or self.now > invitation.grace_end
                    or key in state["reminded"]
                ):
                    continue
                departure = invitation.start - self.travel_seconds(
                    self.env.world.locations[who], invitation.place
                )
                if self.now >= departure:
                    state["reminded"].append(key)
                    if (
                        isinstance(self.activities.get(self.current.get(who)), RestActivity)
                        and self.activities[self.current[who]].wake_invitations
                    ):
                        self.leave(who, "Suggested departure time for your confirmed appointment.")
                    self.feedback(
                        who,
                        f"Appointment {invitation.id} at {clock(invitation.start)}: "
                        f"suggested departure {clock(departure)} for {invitation.place}. "
                        "Choose whether to travel; your current operation finishes first.",
                    )

    def boundary(self):
        self.admit_waiters()
        for who, place_id in list(self.env.world.locations.items()):
            activity = self.activities.get(self.current.get(who))
            if isinstance(activity, MoveActivity) and self.now < self.end:
                continue
            if who in self.outside and self.now < self.end:
                continue
            place = self.env.world.places[place_id]
            if self.now >= self.end:
                self.leave(who, "The day closed.")
                self.outside.pop(who, None)
                home = self.env.config.homes[who]
                if place_id != home:
                    self.env.move(who, home, time=self.now // 60, closing=True)
            elif place.kind != PlaceKind.HOME and self.venue_or_work_closed(who, place_id):
                self.close_venue_for(who, place_id)

    async def process(self, scheduled):
        if scheduled.kind == "tool":
            who = scheduled.data["who"]
            pending = self.pending.get(who)
            if (
                pending is None
                or pending.activity != scheduled.data["activity"]
                or pending.token != scheduled.data["token"]
            ):
                return
            del self.pending[who]
            await self.complete_tool(who, pending)
        elif scheduled.kind == "member_end":
            who = scheduled.data["who"]
            active = self.activities.get(self.current.get(who))
            if (
                active
                and active.id == scheduled.data["activity"]
                and active.members[who].end == scheduled.data["until"]
            ):
                self.leave(who, "The activity time budget ended.")
        elif scheduled.kind == "arrival":
            who = scheduled.data["who"]
            active = self.activities.get(self.current.get(who))
            if active and active.id == scheduled.data["activity"]:
                self.arrive(who, active.destination)
        elif scheduled.kind == "assessment":
            await self.assessment(scheduled.data["job"])
        elif scheduled.kind == "invitation_expired":
            invitation = self.invitations[scheduled.data["invitation"]]
            if invitation.status == "pending":
                # Arrival/confirmation exactly at the grace boundary gets one final check.
                self.start_ready_conversations()
                if invitation.status == "pending":
                    invitation.status = "cancelled"
                    self.emit(
                        EventKind.DISCUSSION,
                        "The conversation was cancelled: "
                        "fewer than two confirmed residents arrived free.",
                        actor=invitation.owner,
                        audience=[invitation.owner, *invitation.invited],
                        invitation=invitation.id,
                    )
        elif scheduled.kind == "daily_choice":
            self.daily_choices()
        elif scheduled.kind == "intervention":
            self.sim._intervene(self.now // 60, scheduled.data["payload"])
        else:
            self.boundary()
            self.daily_choices()

    def prepare_day(self, start):
        self.now = start * 60
        self.end = self.sim.config.calendar.end(day_of(start)) * 60
        self.queue = EventQueue()
        for who, intent in list(self.rest_intents.items()):
            if intent["until"] <= self.now:
                del self.rest_intents[who]
                continue
            self.start_rest(who, intent["until"], wake=intent["wake"])
        day = day_of(start)
        self.daily_life = (
            {str(day): self.daily_life[str(day)]} if str(day) in self.daily_life else {}
        )
        for text in ("08:00", "12:00", "14:00", "18:00", "22:00"):
            moment = at(day, text)
            if moment >= self.now:
                self.queue.add(moment, "boundary", priority=2)
        for place in self.env.world.places.values():
            for opening, closing in place.spans():
                for text in (opening, closing):
                    moment = at(day, text)
                    if moment >= self.now:
                        self.queue.add(moment, "boundary", priority=2)
        for job, entry in self.assessments.items():
            self.start_assessment(job)
            self.queue.add(
                max(self.now, entry.get("retry_at", entry["due"])), "assessment", job=job
            )
        for invitation in self.invitations.values():
            if invitation.status == "pending":
                if self.sim.config.lunch_place:
                    for person in invitation.confirmed:
                        self.queue.add(
                            max(
                                self.now,
                                invitation.start
                                - self.travel_seconds(
                                    self.env.world.locations[person], invitation.place
                                ),
                            ),
                            "daily_choice",
                        )
                self.queue.add(
                    max(self.now, invitation.start), "appointment", invitation=invitation.id
                )
                self.queue.add(
                    max(self.now, invitation.grace_end),
                    "invitation_expired",
                    priority=3,
                    invitation=invitation.id,
                )
        while len(self.sim.queue) and self.sim.queue.state()[0].time * 60 <= self.end:
            event = self.sim.queue.pop()
            self.queue.add(event.time * 60, "intervention", priority=1, payload=event.payload)

    async def run(self, start):
        self.prepare_day(start)
        while True:
            # Let background grading run even when every resident is asleep. This yields
            # execution, but never advances or ties simulated time to wall-clock latency.
            await asyncio.sleep(0)
            # All effects at this time finish before any resident gets a new observation.
            due = self.queue.pop_at(self.now)
            claims = [
                e
                for e in due
                if e.kind == "tool"
                and self.pending.get(e.data["who"])
                and self.pending[e.data["who"]].action.tool == "claim"
            ]
            if claims:
                self.sim.rng.shuffle(claims)
                _announce_draws(
                    self.env,
                    [
                        (
                            None,
                            e.data["who"],
                            Decision(
                                thought="",
                                action=ClaimTask(
                                    task_id=self.pending[e.data["who"]].action.arguments["job"],
                                    partner=self.pending[e.data["who"]].action.arguments.get(
                                        "partner"
                                    ),
                                ),
                            ),
                        )
                        for e in claims
                    ],
                    self.now // 60,
                )
                due = [e for e in due if e not in claims] + claims
            for event in due:
                await self.process(event)
            self.env.pair_applicants(self.now // 60, self.sim.rng)
            self.daily_choices()
            self.start_ready_conversations()
            self.wake_rests()
            if self.now >= self.end:
                self.boundary()
                break
            ready = [
                who
                for who in self.sim.agents
                if who not in self.pending
                and who not in self.daily_waiting
                and (
                    who not in self.current
                    or isinstance(
                        self.activities[self.current[who]], WorkActivity | ConversationActivity
                    )
                )
            ]
            if ready:
                await self.decisions(ready)
                self.sim._bound_lapses()
            immediately_ready = any(
                who not in self.pending
                and who not in self.daily_waiting
                and (
                    who not in self.current
                    or isinstance(
                        self.activities[self.current[who]], WorkActivity | ConversationActivity
                    )
                )
                for who in self.sim.agents
            )
            if immediately_ready:
                continue
            if self.queue.events and self.queue.next_time() == self.now:
                continue
            next_time = self.queue.next_time()
            if next_time < self.now:
                raise RuntimeError("The event clock moved backwards")
            self.now = next_time
            self.transitions.clear()
        self.sim.activity_state = self.state()

    async def close(self):
        for future in self.futures.values():
            future.cancel()
        await asyncio.gather(*self.futures.values(), return_exceptions=True)
        self.futures.clear()
