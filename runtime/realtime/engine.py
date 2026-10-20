"""Shared real-time activities. Residents never wait for a batch of model responses."""

import asyncio
import hashlib
import inspect
from dataclasses import dataclass, field
from uuid import uuid4

from core.environment.rejection import Rejected
from core.interaction import ClaimTask, Decision, EventKind, SubmitWork, day_of
from core.interaction.actions import Activity as Choice
from infrastructure.llm import StructuredOutputError
from runtime.activities.engine import ActivityEngine, ActivityLoopError
from runtime.activities.model import (
    ConversationActivity,
    Handoff,
    Message,
    MoveActivity,
    WorkActivity,
    at,
    clock,
)
from runtime.realtime.clock import WallClock
from runtime.scenes.scene import _announce_draws, lapse

REPOSITORY = {"read_code", "search", "diff", "edit", "command", "test"}


@dataclass
class Finished:
    value: object
    end: int
    wall_seconds: float


@dataclass
class Running:
    task: asyncio.Task
    kind: str
    activity: str | None
    start: int
    action: Choice | None = None
    task_id: str | None = None
    continuation: object | None = None
    invalidated: bool = False
    cancel_recorded: bool = False
    targets: tuple[str, ...] = ()
    decision_id: str = ""
    request_id: str = ""
    causes: list = field(default_factory=list)


class RealtimeEngine(ActivityEngine):
    def __init__(self, simulation, state=None, *, wall_clock=None):
        super().__init__(simulation, state)
        self.settings = simulation.config.realtime
        self.clock = wall_clock or WallClock(self.settings.multiplier)
        self.running: dict[str, Running] = {}
        self.closing: set[str] = set()
        self.deferred: dict[str, str] = {}
        self.speech_times = {}
        # Recording-only rest: current remains empty so selection and invitation
        # readiness retain their existing semantics, rather than behaving like sleep.
        self.selection_rests = {}
        self._lifecycle_transition = False

    def begin_selection_rest(self, who):
        if who in self.current or who in self.selection_rests or self.now >= self.end:
            return
        ident = self.identifier("choosing")
        self.selection_rests[who] = (ident, self.now)
        self.emit(
            EventKind.ACTIVITY_ENTERED,
            f"{who} is choosing the next activity.",
            actor=who,
            audience=[],  # Bookkeeping must not add artificial experiences to memory.
            activity=ident,
            activity_type="rest",
            phase="choosing_next_activity",
            start=self.now / 60,
            end=None,
            participants=[who],
            outside=who in self.outside,
        )

    def end_selection_rest(self, who, reason):
        entry = self.selection_rests.pop(who, None)
        if entry is None:
            return
        ident, start = entry
        self.emit(
            EventKind.ACTIVITY_LEFT,
            f"{who} stopped choosing the next activity: {reason}",
            actor=who,
            audience=[],
            activity=ident,
            activity_type="rest",
            phase="choosing_next_activity",
            reason=reason,
            start=start / 60,
            end=self.now / 60,
        )

    def emit(self, kind, text, *, actor=None, audience=None, **payload):
        # Enter has already validated and registered the new membership. Close the
        # transition first in the log, only after entry is known to have succeeded.
        if kind == EventKind.ACTIVITY_ENTERED and not payload.get("phase"):
            self.end_selection_rest(actor, "Next activity started.")
        event = super().emit(kind, text, actor=actor, audience=audience, **payload)
        if kind == EventKind.ACTIVITY_LEFT:
            for who, job in list(self.running.items()):
                if self.activities.get(job.activity) and self.activities[
                    job.activity
                ].interrupts_reply(event, job.targets):
                    self.invalidate_decision(who, event=event, changed_fields=["reply_targets"])
        return event

    def prepare_day(self, start):
        super().prepare_day(start)
        for who in self.sim.agents:
            self.begin_selection_rest(who)

    def retire_work(self):
        for activity in self.activities.values():
            if not isinstance(activity, WorkActivity) or not activity.task_id:
                continue
            claim = self.env.board.claims.get(activity.task_id)
            for who in list(activity.participants):
                if claim is None or who not in claim.workers:
                    if who in self.running:
                        self.deferred[who] = "This job is no longer assigned to you."
                    else:
                        self.leave(who, "This job is no longer assigned to you.")
            if claim is None and not activity.participants:
                activity.status = "ended"

    def available(self, who):
        return who not in self.running and super().available(who)

    def state(self):
        return {**super().state(), "last_time": self.now}

    def menu(self, who):
        menu = super().menu(who)
        menu["realtime"] = True
        active = self.activities.get(self.current.get(who))
        if isinstance(active, ConversationActivity):
            menu.update(
                reply_phase="intent", reply_targets=[p for p in active.participants if p != who]
            )
        if "tools" in menu:
            # Availability is checked at launch, not by a guessed future duration.
            tools = set(menu["tools"]) | set(menu["blocked"])
            tools -= {"read"}
            menu.update(tools=sorted(tools), costs={}, blocked={})
        return menu

    def clock_rules(self):
        return (
            f"One real second advances {self.settings.multiplier:g} town seconds. "
            "Thinking and work take their actual elapsed time. "
            "Work continues until you leave or coding hours close; "
            "conversation continues until you leave or the venue closes. "
            "an operation already started may finish after coding closes. "
            "You hear completed speech directly. Rest and travel take their stated time."
        )

    def activity_context(self, who, active, menu):
        if active is None:
            return []
        context = [
            f"You are participating in {active.kind} {active.id}. "
            f"Latest end: {clock(active.members[who].end)}."
        ]
        if isinstance(active, ConversationActivity):
            context.append(f"Topic: {active.topic}.")
        return context

    def select(self, who, action):
        if self.now >= self.end:
            raise Rejected("The day has closed.")
        if action.operation in ("select_work", "resume_work", "select_conversation"):
            action = action.model_copy(update={"seconds": max(1, self.end - self.now)})
        return super().select(who, action)

    def invitation_action(self, who, tool, args):
        # Only venue/day closing bounds a conversation; no arbitrary 30-minute cap.
        if tool == "invite":
            args = {**args, "minutes": max(1, (self.end - self.now + 59) // 60)}
        return super().invitation_action(who, tool, args)

    def timed_task(self, factory):
        started = self.clock.monotonic()

        async def run():
            value = await factory()
            return Finished(value, self.clock.now(), self.clock.monotonic() - started)

        return asyncio.create_task(run())

    def start_decision(self, who, previous=None, *, targets=()):
        self.begin_selection_rest(who)
        activity_id = self.current.get(who)
        agent = self.sim.agents[who]
        method = agent.choose_tool if activity_id else agent.choose_activity
        supports_continuation = "continuation" in inspect.signature(method).parameters
        continuation = previous.continuation if previous else None
        if previous and previous.targets and not targets:
            active = self.activities.get(activity_id)
            if active and all(p in active.participants for p in previous.targets):
                targets = previous.targets
            elif continuation is not None:
                continuation.reply_draft = continuation.messages
        if supports_continuation and continuation is None:
            from core.agent import DecisionContinuation

            continuation = DecisionContinuation()

        async def ask():
            # Consume incoming percepts only once the task actually starts. A task
            # cancelled before its first turn must leave them queued.
            observation = self.observation(who)
            if targets:
                allowance = observation.allowed[0]
                allowance = allowance.model_copy(
                    update={
                        "menu": {
                            **allowance.menu,
                            "reply_phase": "body",
                            "reply_targets": list(targets),
                        }
                    }
                )
                observation = observation.model_copy(
                    update={
                        "allowed": (allowance,),
                        "situation": observation.situation
                        + "\nAddressed members: "
                        + ", ".join(targets)
                        + ". Write only the words you will say to these members in the text field.",
                    }
                )
            try:
                if supports_continuation:
                    return await method(observation, continuation=continuation)
                return await method(observation)
            except StructuredOutputError as error:
                return error

        self.running[who] = Running(
            self.timed_task(ask),
            "decision",
            activity_id,
            previous.start if previous else self.now,
            continuation=continuation,
            targets=tuple(targets),
            decision_id=previous.decision_id if previous else uuid4().hex,
            request_id=uuid4().hex,
        )
        job = self.running[who]
        if continuation is not None:
            continuation.metadata = {
                "decision_id": job.decision_id,
                "request_id": job.request_id,
                "decision_phase": "reply_body" if targets else "intent",
            }

    def invalidate_decision(self, who, *, event=None, changed_fields=()):
        job = self.running.get(who)
        if not job or job.kind != "decision" or not job.targets:
            return
        active = self.activities.get(job.activity)
        if event is not None and (not active or not active.interrupts_reply(event, job.targets)):
            return
        if event is not None:
            job.causes.append(
                {
                    "event_id": event.seq,
                    "event_type": str(event.kind),
                    "changed_fields": list(changed_fields),
                }
            )
        if not job.invalidated:
            job.invalidated = True
            job.task.cancel()

    def interruption_stop(self, who, job):
        active = self.activities.get(job.activity)
        return (
            self.current.get(who) != job.activity
            or not active
            or active.status == "ended"
            or job.activity in self.closing
            or who in self.deferred
            or self.now >= self.end
        )

    def record_decision_cancel(self, who, job, *, stop, changed_fields=()):
        if job.cancel_recorded:
            return
        job.cancel_recorded = True
        self.emit(
            EventKind.TOOL_CANCELLED,
            "Reply generation stopped." if stop else "Reply generation interrupted.",
            actor=who,
            audience=[],
            activity=job.activity,
            tool="reply" if job.targets else "decision",
            decision_id=job.decision_id,
            request_id=job.request_id,
            mode="stop" if stop else "resume",
            causes=job.causes,
            changed_fields=sorted(
                {*changed_fields, *(f for c in job.causes for f in c["changed_fields"])}
            ),
            event_ids=[c["event_id"] for c in job.causes],
        )

    async def restart_decision(self, who, job):
        await asyncio.gather(job.task, return_exceptions=True)
        stop = self.interruption_stop(who, job)
        self.record_decision_cancel(who, job, stop=stop)
        del self.running[who]
        if not stop:
            self.start_decision(who, job)

    async def refresh_decisions(self):
        for who, job in list(self.running.items()):
            if job.kind == "decision" and job.invalidated:
                await self.restart_decision(who, job)

    def schedule(self, who, action):
        if who in self.running:
            raise Rejected("Finish your current operation first.")
        if action.operation == "activity_tool" and action.tool == "help":
            return self.show_help(who)
        if who not in self.current or action.operation == "select_rest":
            return self.select(who, action)
        if self.now >= self.end or self.current[who] in self.closing or who in self.deferred:
            raise Rejected("The activity is closing; no new operation may start.")
        menu = self.menu(who)
        if action.operation != "activity_tool" or action.tool not in menu["tools"]:
            raise Rejected("Choose an available tool in your current activity.")
        choices = {
            "claim": ("job", "jobs"),
            "accept": ("invitation", "accept_invitations"),
            "decline": ("invitation", "invitations"),
            "defer": ("invitation", "defer_invitations"),
        }
        if action.tool in choices:
            argument, offered = choices[action.tool]
            if action.arguments.get(argument) not in menu.get(offered, ()):
                raise Rejected(
                    "That choice is no longer available; choose from the current situation."
                )
        # Reuse input bounds, never its estimated cost. Reading conversation is not offered.
        self.prepare(who, action)
        claim = self.env.board.claim_of(who)
        task_id = claim.task.id if claim else None
        activity = self.activities[self.current[who]]
        part = claim.task.parts[0] if claim else None
        provider = self.env.providers[claim.task.trade] if claim else None

        async def execute():
            tool, args = action.tool, action.arguments
            if tool == "wait":
                await asyncio.sleep(
                    min(int(args["seconds"]), max(0, self.end - self.now))
                    / self.settings.multiplier
                )
                return None
            if tool in REPOSITORY:
                return await provider.run_command(part, who, task_id, self.command_for(tool, args))
            if tool == "submit":
                return await provider.prepare_submission(part, who, task_id, "WORKTREE")
            if tool == "handoff":
                return await provider.export_handoff(part, who, task_id)
            if tool == "apply_handoff":
                return await provider.apply_handoff(
                    part, who, task_id, self.handoffs[args["handoff"]].patch
                )
            return None

        self.running[who] = Running(
            self.timed_task(execute), "tool", activity.id, self.now, action, task_id
        )
        self.emit(
            EventKind.TOOL_STARTED,
            f"{who} began {action.tool}.",
            actor=who,
            activity=activity.id,
            tool=action.tool,
            arguments=action.arguments,
            start=self.now / 60,
            end=None,
            timing="wall",
        )

    def daily_choices(self):
        self._lifecycle_transition = True
        try:
            super().daily_choices()
        finally:
            self._lifecycle_transition = False

    def leave(self, who, reason):
        activity = self.activities.get(self.current.get(who))
        if who in self.running:
            self.deferred[who] = reason
            return
        targeted = (
            not self._lifecycle_transition
            and isinstance(activity, ConversationActivity)
            and any(
                who in job.targets and job.activity == activity.id for job in self.running.values()
            )
        )
        if (
            isinstance(activity, ConversationActivity)
            and len(activity.participants) <= 2
            and not targeted
        ):
            for person in activity.participants:
                job = self.running.get(person)
                if job and job.action and job.action.tool == "wait":
                    job.task.cancel()
            if any(p in self.running for p in activity.participants):
                self.closing.add(activity.id)
                self.deferred[who] = reason
                return
        super().leave(who, reason)
        self.remember(who)
        self.begin_selection_rest(who)

    def remember(self, who):
        pending = self.running.get(who)
        if pending and pending.kind == "decision":
            # Agent.act appends the intention at its observation time after inference.
            # Keep arriving speech queued until that append, then ingest it immediately;
            # otherwise the persistent episodic stream would move backwards in time.
            return
        agent = self.sim.agents.get(who)
        if hasattr(agent, "perceive"):
            agent.perceive(self.env.perceive(who))

    def speak(self, who, text, activity):
        audience = tuple(
            p
            for p in self.conversation_audience(activity)
            if self.env.world.locations[p] == activity.place
            and (p in self.outside) == activity.outside
        )
        message = Message(
            id=len(activity.messages), author=who, sent_at=self.now, text=text, audience=audience
        )
        activity.messages.append(message)
        generation = self.speech_times.pop(who, {})
        event = self.emit(
            EventKind.SPEECH,
            f'{who} says: "{text}"',
            actor=who,
            audience=list(audience),
            activity=activity.id,
            participants=list(activity.participants),
            message=message.model_dump(mode="json"),
            **generation,
        )
        for person in audience:
            if person in activity.participants:
                activity.members[person].cursor = len(activity.messages)
                self.sim._met[person].update(p for p in activity.participants if p != person)
            job = self.running.get(person)
            if person != who and job and job.activity == activity.id:
                self.invalidate_decision(
                    person, event=event, changed_fields=["conversation_speech"]
                )
            self.remember(person)
            waiting = self.running.get(person)
            if waiting and waiting.action and waiting.action.tool == "wait":
                waiting.task.cancel()

    async def commit_tool(self, who, job, finished):
        action, result = job.action, finished.value
        tool, args = action.tool, action.arguments
        activity = self.activities[job.activity]
        if tool in REPOSITORY:
            event = self.emit(
                EventKind.COMMAND_EXECUTED,
                f"At your desk the terminal returned exit code {result['exit_code']}:\n"
                f"{result['output']}",
                actor=who,
                activity=activity.id,
                task_id=job.task_id,
                part=1,
                command=self.command_for(tool, args),
                **result,
            )
            activity.feedback[who] = [event.text[-16000:]]
            activity.history.append(
                {
                    "time": self.now,
                    "worker": who,
                    "tool": tool,
                    "task_id": job.task_id,
                    "feedback": activity.feedback[who],
                }
            )
        elif tool == "reply":
            if self.current.get(who) != activity.id or any(
                p not in activity.participants for p in args.get("targets", ())
            ):
                raise Rejected("The addressed members are no longer in this conversation.")
            self.speak(who, args["text"], activity)
        elif tool == "submit":
            claim = self.env.board.claim_of(who)
            if not claim or claim.task.id != job.task_id or job.task_id in self.assessments:
                raise Rejected("This job is no longer available for submission.")
            action = SubmitWork(task_id=job.task_id, solution=result, report=args["report"])
            due = self.now + self.timing.assessment_seconds
            self.assessments[job.task_id] = {
                "due": due,
                "agent": who,
                "action": action.model_dump(mode="json"),
                "place": activity.place,
                "delayed": False,
            }
            self.start_assessment(job.task_id)
            self.queue.add(due, "assessment", job=job.task_id)
            self.emit(
                EventKind.SUBMISSION_PENDING,
                "Repair submitted for background assessment. "
                + self.assessment_waiting(who).strip(),
                actor=who,
                audience=list(claim.workers),
                task_id=job.task_id,
                due_seconds=due,
            )
            self.leave(who, "Repair submitted for background assessment.")
        elif tool == "handoff":
            handoff = Handoff(
                id=self.identifier("handoff"),
                task_id=job.task_id,
                sender=who,
                recipient=args["to"],
                patch=result,
                description=args["description"],
                created_at=self.now,
                version=hashlib.sha256(result.encode()).hexdigest(),
            )
            self.handoffs[handoff.id] = handoff
            relay = self.relay_session(job.task_id)
            if relay:
                relay.relay_owner = None
            self.emit(
                EventKind.CODE_HANDOFF,
                f"{who} offered code: {handoff.description}",
                actor=who,
                audience=[who, handoff.recipient],
                task_id=job.task_id,
                handoff=handoff.id,
                version=handoff.version,
                patch=handoff.patch,
            )
        elif tool == "apply_handoff":
            handoff = self.handoffs[args["handoff"]]
            if result["exit_code"]:
                self.feedback(
                    who,
                    "Handoff conflict; the previous workspace was preserved.\n" + result["output"],
                )
            else:
                handoff.status = "accepted"
                relay = self.relay_session(job.task_id)
                if relay:
                    relay.relay_owner = who
                self.emit(
                    EventKind.CODE_HANDOFF,
                    f"{who} applied {handoff.id}.",
                    actor=who,
                    audience=[who, handoff.sender],
                    task_id=job.task_id,
                    handoff=handoff.id,
                    applied=True,
                )
        elif tool == "wait":
            pass
        else:
            # Environment-only operations have no artificial execution charge.
            from runtime.activities.engine import PendingTool

            await super().complete_tool(
                who,
                PendingTool(job.activity, job.action, job.start, self.now, {}),
                record_completion=False,
            )
        self.emit(
            EventKind.TOOL_COMPLETED,
            f"{who} finished {tool}.",
            actor=who,
            activity=job.activity,
            tool=tool,
            start=job.start / 60,
            end=self.now / 60,
            wall_seconds=finished.wall_seconds,
            multiplier=self.settings.multiplier,
            elapsed_sim_seconds=self.now - job.start,
        )

    async def finish(self, who, job):
        if job.kind == "decision" and job.invalidated:
            await self.restart_decision(who, job)
            return
        del self.running[who]
        if job.task.cancelled():
            if job.action:
                self.emit(
                    EventKind.TOOL_COMPLETED,
                    "Waiting ended on speech or conversation closure.",
                    actor=who,
                    activity=job.activity,
                    tool=job.action.tool,
                    start=job.start / 60,
                    end=self.now / 60,
                )
            return
        finished = job.task.result()
        if job.kind == "decision":
            wall_seconds = (self.now - job.start) / self.settings.multiplier
            daily_boundary = self.sim.config.lunch_place and any(
                job.start < at(day_of(self.now // 60), text) <= self.now
                for text in ("12:00", "18:00")
            )
            reply = finished.value
            if isinstance(reply, StructuredOutputError):
                lapse(self.env, who, reply, time=self.now // 60)
                self.leave(who, "No valid model decision.")
                if self.now < self.end:
                    self.select(
                        who,
                        Choice(
                            operation="select_rest",
                            arguments={"until": clock(self.end), "wake": True},
                        ),
                    )
                return
            if self.current.get(who) != job.activity:
                raise Rejected("The activity changed before this decision could be used.")
            action = reply.action
            if isinstance(action, Choice) and action.tool == "reply":
                active = self.activities.get(self.current.get(who))
                targets = tuple(dict.fromkeys(action.arguments.get("targets", ())))
                if (
                    not isinstance(active, ConversationActivity)
                    or not targets
                    or any(p == who or p not in active.participants for p in targets)
                ):
                    raise Rejected("Choose current conversation members to address.")
                if not job.targets:
                    if self.interruption_stop(who, job):
                        self.remember(who)
                        return
                    if "text" in action.arguments:
                        raise Rejected("Choose whom to address before writing your reply.")
                    if job.continuation is not None:
                        job.continuation.messages = job.continuation.reply_draft
                        job.continuation.reply_draft = ()
                    self.start_decision(who, job, targets=targets)
                    return
                if targets != job.targets:
                    raise Rejected("Keep the addressed members chosen for this reply.")
                self.prepare(who, action)
            if isinstance(action, Choice) and action.tool == "reply":
                self.speech_times[who] = {
                    "addressed_targets": list(job.targets),
                    "decision_id": job.decision_id,
                    "request_id": job.request_id,
                    "generation_start": job.start,
                    "generation_end": self.now,
                    "generation_wall_seconds": wall_seconds,
                }
            recorded_action = action.model_dump(mode="json")
            if isinstance(action, Choice):
                for unused in ("minutes", "seconds", "until", "remote", "topic"):
                    recorded_action.pop(unused, None)
            self.emit(
                EventKind.DECISION,
                f"{who} chose {action.kind}.",
                actor=who,
                decision_id=job.decision_id,
                request_id=job.request_id,
                thought=reply.thought,
                action=recorded_action,
                layer="activity_tool" if job.activity else "choose_activity",
                start=job.start / 60,
                end=self.now / 60,
                wall_seconds=wall_seconds,
                multiplier=self.settings.multiplier,
                elapsed_sim_seconds=self.now - job.start,
            )
            current = self.current.get(who)
            if current != job.activity:
                return  # An invitation/boundary changed the original decision's context.
            closing = (
                daily_boundary
                or self.now >= self.end
                or current in self.closing
                or who in self.deferred
            )
            if closing:
                # The speech itself was being generated before closing; deliver it before exit.
                if isinstance(action, Choice) and action.tool == "reply" and current:
                    activity = self.activities[current]
                    if isinstance(activity, ConversationActivity):
                        if job.continuation is not None:
                            job.continuation.commit()
                        self.speak(who, action.arguments["text"], activity)
                        self.remember(who)
                return
            if not isinstance(action, Choice):
                raise Rejected("Choose an activity or an available activity tool.")
            key = (self.now, who)
            self.transitions[key] = self.transitions.get(key, 0) + 1
            if self.transitions[key] > self.timing.max_zero_transitions:
                raise ActivityLoopError(f"{who} repeatedly acted without advancing the wall clock")
            self.schedule(who, action)
            if job.continuation is not None:
                job.continuation.commit()
            self.remember(who)
        else:
            await self.commit_tool(who, job, finished)

    def boundary(self):
        if self.now >= self.end:
            for who in list(self.selection_rests):
                self.end_selection_rest(who, "The day closed.")
        self.admit_waiters()
        for who, place in list(self.env.world.locations.items()):
            activity = self.activities.get(self.current.get(who))
            if isinstance(activity, MoveActivity) and self.now < self.end:
                continue
            if who in self.outside and self.now < self.end:
                continue
            closed = self.now >= self.end or self.venue_or_work_closed(who, place)
            if not closed:
                continue
            if isinstance(activity, ConversationActivity):
                for person in activity.participants:
                    job = self.running.get(person)
                    if job and job.action and job.action.tool == "wait":
                        job.task.cancel()
            if isinstance(activity, ConversationActivity) and any(
                p in self.running for p in activity.participants
            ):
                self.closing.add(activity.id)
                continue
            if who in self.running:
                self.deferred[who] = "The place or day closed; finish the started operation."
                continue
            if self.now >= self.end:
                self.leave(who, "The day closed.")
                self.outside.pop(who, None)
                home = self.env.config.homes[who]
                if place != home:
                    self.env.move(who, home, time=self.now // 60, closing=True)
            else:
                self.close_venue_for(who, place)

    def flush_leaves(self):
        for ident in list(self.closing):
            activity = self.activities[ident]
            if any(p in self.running for p in activity.participants):
                continue
            for who in list(activity.participants):
                self.deferred.pop(who, None)
                if self.current.get(who) != ident:
                    continue  # Another participant's exit may have completed this transition.
                super().leave(who, "Conversation ended after all started speech was delivered.")
                self.remember(who)
                self.begin_selection_rest(who)
            self.closing.remove(ident)
        for who, reason in list(self.deferred.items()):
            if who not in self.running:
                self.deferred.pop(who)
                self.leave(who, reason)
        self.retire_work()
        self.boundary()

    async def run(self, start):
        self.prepare_day(start)
        self.clock.rebase(self.now)
        day = day_of(start)
        try:
            while True:
                await asyncio.sleep(0)
                target = self.clock.now()
                if day_of(target // 60) != day:
                    raise RuntimeError(
                        "A started operation exceeded the civil day; "
                        "refusing a backward night clock"
                    )
                await self.refresh_decisions()
                # Apply completions and timers in one chronological stream.
                while True:
                    done = [(who, j) for who, j in self.running.items() if j.task.done()]

                    def end_of(item):
                        task = item[1].task
                        return (
                            self.now if task.cancelled() or task.exception() else task.result().end
                        )

                    done.sort(key=end_of)
                    timer = self.queue.next_time() if self.queue.events else float("inf")
                    completion = end_of(done[0]) if done else float("inf")
                    if min(timer, completion) > target:
                        break
                    self.now = max(self.now, int(min(timer, completion)))
                    if completion <= timer:
                        batch = [done[0]]
                        if done[0][1].action and done[0][1].action.tool == "claim":
                            batch = [
                                (who, job)
                                for who, job in done
                                if end_of((who, job)) == completion
                                and job.action
                                and job.action.tool == "claim"
                            ]
                            self.sim.rng.shuffle(batch)
                            _announce_draws(
                                self.env,
                                [
                                    (
                                        None,
                                        who,
                                        Decision(
                                            thought="",
                                            action=ClaimTask(
                                                task_id=job.action.arguments["job"],
                                                partner=job.action.arguments.get("partner"),
                                            ),
                                        ),
                                    )
                                    for who, job in batch
                                ],
                                self.now // 60,
                            )
                        for who, job in batch:
                            try:
                                await self.finish(who, job)
                            except (Rejected, ValueError, KeyError) as error:
                                if job.action:
                                    self.reject(who, job.action, str(error))
                                else:
                                    self.feedback(who, str(error))
                    else:
                        for event in self.queue.pop_at(timer):
                            active = self.activities.get(self.current.get(event.data.get("who")))
                            if event.kind == "member_end" and isinstance(
                                active, WorkActivity | ConversationActivity
                            ):
                                self.boundary()  # Only hard closing bounds work/chat here.
                            else:
                                await self.process(event)
                self.now = max(self.now, target)
                self.flush_leaves()
                self.daily_choices()
                self.env.pair_applicants(self.now // 60, self.sim.rng)
                await self.refresh_decisions()
                if self.now < self.end:
                    self.start_ready_conversations()
                    self.wake_rests()
                    for who in self.sim.agents:
                        activity = self.activities.get(self.current.get(who))
                        if (
                            who not in self.running
                            and who not in self.deferred
                            and (
                                activity is None
                                or isinstance(activity, WorkActivity | ConversationActivity)
                            )
                            and (not activity or activity.id not in self.closing)
                        ):
                            self.start_decision(who)
                elif not self.running:
                    break
                self.sim._bound_lapses()
                next_timer = self.queue.next_time() if self.queue.events else self.now + 1
                timeout = min(self.settings.poll_seconds, self.clock.delay(next_timer))
                if self.now >= self.end:
                    timeout = self.settings.poll_seconds
                tasks = [j.task for j in self.running.values()]
                if tasks:
                    await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                else:
                    await asyncio.sleep(timeout)
        finally:
            if self.running:
                await self.close_running()
        self.sim.activity_state = self.state()

    async def settle_final(self):
        """Bounded wall wait; an unfinished final assessment stays explicitly resumable."""
        for job in self.assessments:
            self.start_assessment(job)
        self.clock.rebase(self.now)
        deadline = self.clock.monotonic() + self.settings.final_grading_wait_seconds
        await asyncio.sleep(0)
        while self.assessments:
            self.now = max(self.now, self.clock.now())
            for job, entry in list(self.assessments.items()):
                self.start_assessment(job)
                future = self.futures.get(job)
                if future is not None and future.done() and entry["due"] <= self.now:
                    await self.assessment(job)
            if not self.assessments:
                break
            remaining = deadline - self.clock.monotonic()
            if remaining <= 0:
                break
            pending = [task for task in self.futures.values() if not task.done()]
            due = [
                max(entry["due"], entry.get("retry_at", entry["due"]))
                for job, entry in self.assessments.items()
                if job not in self.futures or self.futures[job].done()
            ]
            timeout = min(remaining, self.clock.delay(min(due))) if due else remaining
            if pending:
                await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            else:
                await asyncio.sleep(timeout)
        self.retire_work()
        return bool(self.assessments)

    async def close_running(self):
        tasks = [j.task for j in self.running.values()]
        for who, job in self.running.items():
            if not job.task.done():
                job.task.cancel()
                if job.kind == "decision":
                    self.record_decision_cancel(
                        who, job, stop=True, changed_fields=["scheduler_state"]
                    )
        await asyncio.gather(*tasks, return_exceptions=True)
        self.running.clear()
        for who in list(self.selection_rests):
            self.end_selection_rest(who, "The scheduler stopped.")

    async def close(self):
        await self.close_running()
        await super().close()
