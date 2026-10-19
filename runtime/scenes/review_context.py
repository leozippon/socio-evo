"""Mandatory review evidence drawn only from events the reviewer could receive."""

from collections.abc import Sequence

from core.interaction import Event, EventKind, clock_of, day_of

WORK = {
    EventKind.TASK_CLAIMED,
    EventKind.SUBMISSION_PENDING,
    EventKind.WORK_CHECKED,
    EventKind.WORK_SUBMITTED,
    EventKind.WORK_DELAYED,
    EventKind.TASK_EXPIRED,
}


def work_review_context(events: Sequence[Event], who: str, time: int) -> str:
    # Retain prior-day assignment notices to attribute today's joint submissions correctly.
    visible = [e for e in events if e.time <= time and who in e.audience]
    assignments = {}
    payments = []
    own = []
    observed = []
    for event in visible:
        percept = event.percept(who)
        task = percept.task_id
        if task and event.kind == EventKind.TASK_CLAIMED:
            assignments[task] = event.payload.get("workers", [])
        if day_of(event.time) != day_of(time):
            if event.kind == EventKind.TASK_EXPIRED:
                assignments.pop(task, None)
            continue
        if event.kind == EventKind.PAYMENT and event.payload.get("agent") == who:
            payments.append(event)
        if event.kind not in WORK or not task:
            continue
        is_own = who in assignments.get(task, []) or event.actor == who
        (own if is_own else observed).append(event)
        if event.kind == EventKind.TASK_EXPIRED:
            assignments.pop(task, None)

    def lines(records):
        return (
            "\n".join(
                f"- {clock_of(e.time)} [event:{e.seq}, {e.kind.value}, "
                f"{e.percept(who).task_id}, actor={e.actor or 'environment'}]: "
                + e.percept(who).text
                for e in records
            )
            or "- No matching records delivered to you today; this is not proof nothing happened."
        )

    return "\n\n".join(
        [
            "Verified personal work records for today's peer review. These are environment "
            "receipts/notices you were entitled to receive, not generated recollections. "
            "An intention or a statement in conversation is not proof of execution. "
            "A submitted repair is not accepted until its actual acceptance notice arrives.",
            "YOUR task and acceptance records today (includes joint work assigned to you):\n"
            + lines(own),
            "YOUR personal payment receipts today (not your starting balance or a partner's "
            "separate payment):\n" + lines(payments),
            "OTHER PEOPLE'S work you witnessed today — observations, NOT work you performed "
            "and NOT your earnings:\n" + lines(observed),
            "Use these attributed records when describing your day. Do not count a witnessed "
            "job as your own. Rate only the permitted peers based on your actual interactions; "
            "the records do not prescribe a rating or reveal private code, thoughts "
            "or hidden tests.",
        ]
    )
