"""Reviews retain own verified work and separate witnessed work without leaking truth."""

from core.interaction import Event, EventKind, time_at
from runtime.scenes.review import Review
from runtime.scenes.review_context import work_review_context
from tests.runtime.activities import test_engine as base

engine = base.engine


def event(seq, kind, text, *, actor=None, who=("Mei",), day=1, task="task-1", **payload):
    return Event(
        seq=seq,
        time=time_at(day, "10:00"),
        kind=kind,
        text=text,
        actor=actor,
        audience=who,
        payload={"task_id": task, **payload},
    )


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_own_success_and_payment_are_separate_from_observed_peers():
    events = [
        event(0, EventKind.TASK_CLAIMED, "Mei took job 1", actor="Mei", workers=["Mei"]),
        event(
            1,
            EventKind.WORK_SUBMITTED,
            "Your job 1 passed the client's checks",
            actor="Mei",
            solution="HIDDEN_PATCH",
        ),
        event(2, EventKind.PAYMENT, "You received $60 for job 1", agent="Mei", amount=60),
        event(
            3,
            EventKind.TASK_CLAIMED,
            "Olga took job 2",
            actor="Olga",
            task="task-2",
            workers=["Olga"],
        ),
        event(4, EventKind.WORK_SUBMITTED, "Olga's job 2 passed", actor="Olga", task="task-2"),
        event(
            5, EventKind.PAYMENT, "PRIVATE_OLGA_BALANCE", who=("Olga",), task="task-2", agent="Olga"
        ),
        event(6, EventKind.WORK_ASSESSED, "HIDDEN_GRADING", who=(), quality=1),
        event(7, EventKind.WORK_SUBMITTED, "FUTURE_RESULT", actor="Mei", day=2),
    ]
    text = work_review_context(events, "Mei", time_at(1, "22:00"))
    own = section(text, "YOUR task", "YOUR personal payment")
    observed = text.split("OTHER PEOPLE'S work", 1)[1]
    assert "Your job 1 passed" in own and "Olga's job 2" not in own
    assert "Olga's job 2 passed" in observed and "Your job 1 passed" not in observed
    assert "You received $60" in section(text, "YOUR personal payment", "OTHER PEOPLE'S")
    assert "event:1" in own and "actor=Mei" in own
    assert all(
        secret not in text
        for secret in ["HIDDEN_PATCH", "HIDDEN_GRADING", "PRIVATE_OLGA_BALANCE", "FUTURE_RESULT"]
    )


def test_prior_day_joint_assignment_attributes_partner_delivery_not_partner_income():
    events = [
        event(0, EventKind.TASK_CLAIMED, "Joint job", workers=["Mei", "Tomas"]),
        event(
            1,
            EventKind.SUBMISSION_PENDING,
            "Partner submitted, awaiting assessment",
            actor="Tomas",
            day=2,
        ),
        event(2, EventKind.WORK_SUBMITTED, "Joint repair accepted", actor="Tomas", day=2),
        event(3, EventKind.PAYMENT, "You received $45", agent="Mei", day=2),
        event(4, EventKind.PAYMENT, "Partner private $45", who=("Tomas",), agent="Tomas", day=2),
    ]
    text = work_review_context(events, "Mei", time_at(2, "22:00"))
    own = section(text, "YOUR task", "YOUR personal payment")
    assert "Partner submitted, awaiting assessment" in own and "Joint repair accepted" in own
    assert "Partner private" not in text
    assert "A submitted repair is not accepted" in text


def test_failed_and_delayed_work_not_presented_as_success_or_payment():
    events = [
        event(0, EventKind.TASK_CLAIMED, "You took job 1", workers=["Mei"]),
        event(1, EventKind.WORK_SUBMITTED, "Repair rejected; checks failed", actor="Mei"),
        event(2, EventKind.WORK_DELAYED, "No verdict; retry later", actor="Mei"),
    ]
    text = work_review_context(events, "Mei", time_at(1, "22:00"))
    assert "Repair rejected" in text and "No verdict" in text
    assert "No matching records delivered" in section(
        text, "YOUR personal payment", "OTHER PEOPLE'S"
    )


def test_reassigned_task_no_longer_counts_as_former_workers_success():
    events = [
        event(0, EventKind.TASK_CLAIMED, "You took job 1", workers=["Mei"]),
        event(1, EventKind.TASK_EXPIRED, "Your deadline expired"),
        event(2, EventKind.TASK_CLAIMED, "Olga now took job 1", actor="Olga", workers=["Olga"]),
        event(3, EventKind.WORK_SUBMITTED, "Olga completed job 1", actor="Olga"),
    ]
    text = work_review_context(events, "Mei", time_at(1, "22:00"))
    assert "Olga completed" not in section(text, "YOUR task", "YOUR personal payment")
    assert "Olga completed" in text.split("OTHER PEOPLE'S work")[1]


def test_review_pins_receipts_without_consuming_unread_events(engine):
    engine.env.emit(
        EventKind.TASK_CLAIMED,
        "You took job 1",
        time=time_at(1, "09:00"),
        actor="Mei",
        audience=["Mei"],
        payload={"task_id": "task-1", "workers": ["Mei"]},
    )
    engine.env.emit(
        EventKind.PAYMENT,
        "You received $60",
        time=time_at(1, "10:00"),
        audience=["Mei"],
        payload={"task_id": "task-1", "agent": "Mei"},
    )
    before = engine.env.log.pending_events("Mei")
    review = Review(engine.env, "review", {"Mei": ["Tomas"]}, start=time_at(1, "22:00"))
    assert "You received $60" in review.situation("Mei")
    assert "YOUR task" in review.situation("Mei")
    assert engine.env.log.pending_events("Mei") == before
