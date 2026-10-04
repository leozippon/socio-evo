import pytest
from pydantic import ValidationError

from core.agent import Agent, AgentSeed, CognitionConfig, prompts
from core.agent.memory import Insight, Record, Skill
from core.interaction import Event, Speak, time_at


def test_an_agent_is_a_directory_of_plain_files(tmp_path, script, seed):
    path = tmp_path / "agents" / "Mei"
    Agent.create(path, seed, script.client, CognitionConfig())
    assert sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()) == [
        "memory/episodic.jsonl",
        "memory/insights.jsonl",
        "parameters/model.yaml",
        "parameters/policy.md",
        "profile.yaml",
    ]
    loaded = Agent.load(path, script.client, CognitionConfig())
    assert (loaded.id, loaded.profile) == ("Mei", seed.profile)
    assert loaded.parameters.read_model() == seed.model
    assert loaded.parameters.read_policy() == ""

    with pytest.raises(FileExistsError):
        Agent.create(path, seed, script.client, CognitionConfig())
    with pytest.raises(FileNotFoundError):
        Agent.load(tmp_path / "agents" / "Nobody", script.client, CognitionConfig())
    profile = seed.profile.model_dump()
    for bad in ({**profile, "name": "Mei Lin"}, {**profile, "mood": "calm"}):
        with pytest.raises(ValidationError):
            AgentSeed.model_validate({"profile": bad})
    with pytest.raises(ValidationError, match="L3"):
        AgentSeed.model_validate({"profile": profile, "model": {"adapter": "mei-lora"}})


async def test_act_stores_percepts_and_records_its_own_decision(agent, script, seed, observe):
    observation = observe(1)
    truth = Event(
        **observation.percepts[0].model_dump(),
        audience=("Mei",),
        payload={"note": "TRUTH-ONLY-MARKER"},
    )
    observation = observation.model_copy(update={"percepts": (truth.percept(),)})

    decision = await agent.act(observation)
    assert decision.action == Speak(text="It parses dates now.", to="Ben")
    percept, own = agent.memory.episodic.read()
    assert percept == Record(
        time=truth.time,
        place="office",
        seq=truth.seq,
        text="Ben says: does the parser handle dates?",
    )
    assert (own.time, own.place, own.seq) == (observation.time, "office", None)
    assert (
        own.text == 'I said to Ben: "It parses dates now." I thought: Ben asked about the parser.'
    )

    (request,) = script.requests
    assert request.metadata == {
        "agent": "Mei",
        "purpose": "act",
        "time": observation.time,
        "attempt": 1,
    }
    assert (request.model, request.sampling.temperature) == ("town-model", 0.7)
    system, user = (message.content for message in request.messages)
    identity = f"You are Mei. You are 34 years old. {seed.profile.backstory}"
    known = prompts.KNOWN.format(setting=observation.setting)
    assert system == "\n\n".join([identity, known, prompts.UNRESOLVED])
    assert "08:59: Ben says: does the parser handle dates?" in user
    assert "TRUTH-ONLY-MARKER" not in agent.memory.episodic.path.read_text() + system + user

    later = observe(1, "Ben says: thanks.").model_copy(update={"time": observation.time + 30})
    await agent.act(later)
    then, now = (message.content for message in script.requests[-1].messages)
    assert then == system
    assert (
        now.index("does the parser handle dates")
        < now.index('09:00: I said to Ben: "It parses dates now."')
        < now.index("08:59: Ben says: thanks.")
        < now.index("It is 09:30 on Monday, your first day in town. You are at the office.")
    )

    with pytest.raises(ValueError):
        await agent.act(observation.model_copy(update={"agent": "Ben"}))


async def test_recall_mixes_working_context_relevant_memories_insights_and_skills(
    tmp_path, script, seed, observe
):
    cognition = CognitionConfig(recent_records=2, relevant_records=1, insights=1, skills=1)
    agent = Agent.create(tmp_path / "Mei", seed, script.client, cognition)
    start = time_at(1, "09:00")
    agent.memory.episodic.append(
        [
            Record(time=start, place="office", text="Ben promised to review the date parser."),
            Record(time=start + 10, place="office", text="Chloe talked about the weather."),
            Record(time=start + 20, place="office", text="Lunch was noodles."),
            Record(time=start + 30, place="office", text="Dan went home early."),
        ]
    )
    agent.memory.insights.write(
        [
            Insight(id=1, day=1, text="Chloe pays within a day.", subject="Chloe"),
            Insight(id=2, day=1, text="Mornings at the office are quiet."),
            Insight(id=3, day=1, text="Replies to messages can take a while.", subject="Ben"),
        ]
    )
    for skill in (
        Skill(name="date-parsing", description="Parsing dates.", body="Try ISO 8601 first."),
        Skill(name="cooking-rice", description="Rice at home.", body="Rinse twice."),
    ):
        agent.memory.skills.write(skill)

    await agent.act(observe(2, "Ben says: I looked at the date parser review."))
    system, user = (message.content for message in script.requests[-1].messages)
    assert "Ben promised to review the date parser." in user
    assert "weather" not in user
    assert "Lunch was noodles." in user and "Dan went home early." in user
    assert "Replies to messages can take a while." in user
    assert "Chloe pays" not in user and "Mornings" not in user
    assert "date-parsing: Parsing dates.\nTry ISO 8601 first." in user
    assert "- cooking-rice: Rice at home.\n- date-parsing: Parsing dates." in system
    assert "Rinse twice." not in system + user and "Try ISO" not in system
