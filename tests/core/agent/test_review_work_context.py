"""Own receipts are mandatory review context even when retrieval favors a peer's job."""

import pytest

from core.agent.config import ActiveRecallConfig, ContextBudgetConfig, WorkNotesConfig
from core.interaction import Event, EventKind, MayPass, MayRate, time_at
from infrastructure.llm import ScriptedClient
from runtime.scenes.review_context import work_review_context


@pytest.mark.parametrize("budget", [False, True])
async def test_receipts_survive_peer_biased_retrieval_and_context_packing(agent, observe, budget):
    requests = []

    def answer(request):
        requests.append(request)
        return {
            "thought": "Use my verified receipts, not Olga's earnings",
            "do": "carry on quietly",
        }

    agent.client = ScriptedClient(answer)
    agent.cognition = agent.cognition.model_copy(
        update={
            "active_recall": ActiveRecallConfig(enabled=False),
            "context_budget": ContextBudgetConfig(enabled=budget),
            "work_notes": WorkNotesConfig(enabled=True),
            "recent_records": 1,
            "relevant_records": 0,
        }
    )
    events = [
        Event(
            seq=0,
            time=time_at(1, "09:00"),
            kind=EventKind.TASK_CLAIMED,
            actor="Mei",
            audience=("Mei",),
            text="You took job 1",
            payload={"task_id": "task-1", "workers": ["Mei"]},
        ),
        Event(
            seq=1,
            time=time_at(1, "10:00"),
            kind=EventKind.WORK_SUBMITTED,
            actor="Mei",
            audience=("Mei",),
            text="Your job 1 passed the client's checks",
            payload={"task_id": "task-1"},
        ),
        Event(
            seq=2,
            time=time_at(1, "10:00"),
            kind=EventKind.PAYMENT,
            audience=("Mei",),
            text="The clerk paid you $60 for job 1",
            payload={"task_id": "task-1", "agent": "Mei"},
        ),
        Event(
            seq=3,
            time=time_at(1, "20:00"),
            kind=EventKind.WORK_SUBMITTED,
            actor="Olga",
            audience=("Mei",),
            text="Olga's job 2 passed",
            payload={"task_id": "task-2"},
        ),
    ]
    agent.perceive([e.percept("Mei") for e in events])
    observation = observe(1).model_copy(
        update={
            "time": time_at(1, "22:00"),
            "scene": "day-0001/review",
            "percepts": (),
            "situation": "Review your interaction with Olga.\n"
            + work_review_context(events, "Mei", time_at(1, "22:00")),
            "allowed": (MayRate(whom=("Olga",)), MayPass()),
        }
    )
    await agent.act(observation)
    prompt = requests[-1].messages[-1].content
    assert "YOUR task and acceptance" in prompt
    assert "The clerk paid you $60 for job 1" in prompt
    assert "OTHER PEOPLE'S work" in prompt and "Olga's job 2 passed" in prompt
    assert "Your work notes for job 2" not in prompt
    if budget:
        assert requests[-1].metadata["context_usage"]["input_count"] <= 24000
