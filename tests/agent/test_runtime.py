"""The loop against a scripted model and a fake world."""

import asyncio
import contextlib

import pytest

from agent import texts
from agent.compaction import INSTRUCTION
from agent.port import ToolResult, ToolSpec
from agent.runtime import Runtime, RuntimeConfig
from agent.session import Session
from agent.testing import FakePort, ScriptedModel, reply, running, tool_call
from infrastructure.llm import LLMBusyError, LLMCallError, Message, ToolCall
from infrastructure.storage import read_jsonl

ANYTHING = {"type": "object", "properties": {}}
SAY = ToolSpec("say", "Say something to those here.", ANYTHING)
GO = ToolSpec("go", "Go somewhere.", ANYTHING)
LOOK = ToolSpec("look_around", "See who and what is here.", ANYTHING)
SHELL = ToolSpec("shell", "Run a command in your workspace.", ANYTHING)


async def settle(port: FakePort) -> None:
    """Until the runtime waits on an empty inbox."""
    await asyncio.wait_for(port.waiting.wait(), 5)


def trace(directory) -> list[dict]:
    return list(read_jsonl(directory.trace_path))


def context(directory) -> list[Message]:
    return [entry.message for entry in Session(directory.session_path).context()]


async def test_a_round_trip_of_tool_calls_ends_in_waiting(directory):
    port = FakePort(tools=[SAY], results={"say": ToolResult("You say it.")})
    write = tool_call("write_file", path="memory/work.md", content="Fixed task 3.")
    say = tool_call("say", text="Morning!")
    model = ScriptedModel(reply("", write, reasoning="Note it."), reply("", say), reply("Done."))
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        await settle(port)

    assert (directory.root / "memory/work.md").read_text() == "Fixed task 3."
    assert port.calls == [("say", {"text": "Morning!"})]
    first, second, third = model.requests
    system = first.messages[0]
    assert system.role == "system"
    assert system.content.startswith(f"{texts.ABOUT_ME}\n\nI am Ana Reyes, thirty-four")
    assert "The workshop opens at 09:00" in system.content
    assert first.messages[-1].content == "Your alarm rings.\n\n" + port.situation_text
    names = [tool["function"]["name"] for tool in first.tools]
    assert names == ["read_file", "write_file", "edit_file", "list_files", "compact", "say"]
    assert third.messages[: len(second.messages)] == second.messages
    roles = ["system", "user", "assistant", "tool", "assistant", "tool"]
    assert [m.role for m in third.messages] == roles
    assert third.messages[3] == Message(
        role="tool", content="Wrote memory/work.md.", tool_call_id=write.id
    )
    assert context(directory)[-1] == Message(role="assistant", content="Done.")
    kinds = [record["kind"] for record in trace(directory)]
    assert kinds == ["percept", "prompt"] + ["request", "reply", "tool_call", "tool_result"] * 2 + [
        "request",
        "reply",
    ]
    assert port.busy == [True, False] * 5 + [False]


async def test_a_rewritten_account_of_oneself_opens_the_next_request(directory):
    edit = tool_call("edit_file", path="background.md", old_text="a programmer", new_text="a baker")
    model = ScriptedModel(reply("", edit), reply("Done."))
    port = FakePort()
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        await settle(port)

    before, after = (request.messages[0].content for request in model.requests)
    assert before.startswith(f"{texts.ABOUT_ME}\n\nI am Ana Reyes, thirty-four, a programmer")
    assert after.startswith(f"{texts.ABOUT_ME}\n\nI am Ana Reyes, thirty-four, a baker")
    assert after.replace("a baker", "a programmer") == before
    assert [r["text"] for r in trace(directory) if r["kind"] == "prompt"] == [before, after]


async def test_unknown_tools_unreadable_arguments_and_failing_tools_are_answered(directory):
    def broken(args):
        raise RuntimeError("the street is missing")

    port = FakePort(tools=[SAY], results={"say": broken})
    garbled = ToolCall(id="g1", name="say", unreadable='{"text": ')
    fly = tool_call("fly", to="moon")
    model = ScriptedModel(reply("", fly, garbled, tool_call("say", text="hi")), reply("Hm."))
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        await settle(port)

    answers = [m.content for m in model.requests[1].messages if m.role == "tool"]
    assert answers == [texts.UNKNOWN_TOOL.format(name="fly"), texts.UNREADABLE, texts.FAILED]
    assert port.calls == [("say", {"text": "hi"})]
    failed = [r for r in trace(directory) if r["kind"] == "tool_result"][-1]
    assert failed["error"] == "RuntimeError: the street is missing"


async def test_a_result_that_ends_the_turn_waits_for_the_world(directory):
    port = FakePort(tools=[GO], results={"go": ToolResult("You set off.", ends_turn=True)})
    model = ScriptedModel(reply("", tool_call("go", place="café")), reply("Coffee."))
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        await settle(port)
        assert len(model.requests) == 1
        port.situation_text = "It is 08:10. You are at the café."
        port.deliver("You arrive at the café.", kind="arrival")
        await settle(port)
    assert len(model.requests) == 2
    assert model.requests[1].messages[-1].content == (
        "You arrive at the café.\n\nIt is 08:10. You are at the café."
    )


async def test_an_interrupting_percept_aborts_the_reply_in_flight(directory):
    long = " ".join(f"word{n}" for n in range(300))
    model = ScriptedModel(reply(long, reasoning="Let me think."), reply("Hello, Ben."), delay=0.01)
    port = FakePort()
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        while not model.requests:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        ben = port.deliver("Ben says: good morning!", interrupt=True)
        await settle(port)

    records = trace(directory)
    (aborted,) = [r for r in records if r["kind"] == "reply" and r["aborted"]]
    assert aborted["reasoning"] == "Let me think." and aborted["text"]
    assert long.startswith(aborted["text"]) and aborted["text"] != long
    (interruption,) = [r for r in records if r["kind"] == "interruption"]
    assert interruption["events"] == [ben.event_id]
    resumed = model.requests[1].messages
    assert [m.role for m in resumed] == ["system", "user", "user"]
    assert resumed[-1].content == "Ben says: good morning!\n\n" + port.situation_text
    assert [m.content for m in context(directory) if m.role == "assistant"] == ["Hello, Ben."]


async def test_a_running_tool_finishes_and_the_calls_after_it_are_not_carried_out(directory):
    async def look(args):
        port.deliver("Ben says: got a minute?", interrupt=True)
        await asyncio.sleep(0.01)
        return ToolResult("You see Ben.")

    port = FakePort(tools=[LOOK, SAY], results={"look_around": look, "say": ToolResult("Said.")})
    model = ScriptedModel(
        reply("", tool_call("look_around"), tool_call("say", text="hi")), reply("Sure.")
    )
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        await settle(port)

    assert port.calls == [("look_around", {})]
    after = model.requests[1].messages
    assert [m.role for m in after] == ["system", "user", "assistant", "tool", "tool", "user"]
    assert [after[3].content, after[4].content] == ["You see Ben.", texts.NOT_CARRIED_OUT]
    assert after[5].content == "Ben says: got a minute?\n\n" + port.situation_text


async def test_percepts_that_come_meanwhile_are_told_ahead_of_the_next_result(directory):
    def look(args):
        port.deliver("Ben arrived.", kind="arrive")
        return ToolResult("You see the street.")

    def wave_meanwhile(request):
        port.deliver("Ana waved.", kind="wave")
        return reply("", tool_call("look_around"), tool_call("say", text="hi"))

    port = FakePort(tools=[LOOK, SAY], results={"look_around": look, "say": ToolResult("Said.")})
    model = ScriptedModel(wave_meanwhile, reply("Done."))
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model)):
        await settle(port)

    after = model.requests[1].messages
    assert [m.role for m in after] == ["system", "user", "assistant", "tool", "tool"]
    assert [after[3].content, after[4].content] == [
        "Ana waved.\n\nYou see the street.",
        "Ben arrived.\n\nSaid.",
    ]
    kinds = [r["kind"] for r in trace(directory)]
    calls = kinds.index("tool_call")
    assert kinds[calls : calls + 6] == ["tool_call", "percept", "tool_result"] * 2
    (shown,) = [r for r in trace(directory) if r["kind"] == "tool_result" and r["name"] == "say"]
    assert shown["text"] == "Said."  # the trace keeps the result itself


async def test_a_long_result_is_shortened_in_the_context_and_kept_whole_in_the_trace(directory):
    output = "x" * 30_000 + "THE END"
    port = FakePort(tools=[SHELL], results={"shell": ToolResult(output)})
    model = ScriptedModel(reply("", tool_call("shell", command="pytest")), reply("Hm."))
    port.deliver("Your alarm rings.")
    config = RuntimeConfig(tool_result_chars=1000)
    async with running(Runtime(directory, port, model, config)):
        await settle(port)

    shortened = model.requests[1].messages[-1].content
    assert len(shortened) < 1100 and shortened.endswith("THE END")
    assert texts.SHORTENED.format(count=len(output) - 1000) in shortened
    (result,) = [r for r in trace(directory) if r["kind"] == "tool_result"]
    assert result["text"] == output


async def test_a_cut_off_reply_is_asked_again_once_at_lower_effort(directory):
    model = ScriptedModel(
        reply("I was going to", cut_off=True),
        reply("Done."),
        reply("Again", tool_call("say", text="hi"), cut_off=True),
        reply("Again and", tool_call("say", text="hi"), cut_off=True),
    )
    port = FakePort(tools=[SAY], results={"say": ToolResult("Said.")})
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model, RuntimeConfig(reasoning_effort="xhigh"))):
        await settle(port)
        port.deliver("Ben says hi.")
        await settle(port)

    efforts = [request.reasoning_effort for request in model.requests]
    assert efforts == ["xhigh", "medium", "xhigh", "medium"]
    assert model.requests[1].messages == model.requests[0].messages
    assert port.calls == []
    assert [(m.role, m.content, m.tool_calls) for m in context(directory)[1:]] == [
        ("assistant", "Done.", ()),
        ("user", "Ben says hi.\n\n" + port.situation_text, ()),
        ("assistant", "Again and", ()),
        ("user", texts.CUT_OFF, ()),
    ]
    cut = [r for r in trace(directory) if r["kind"] == "reply" and r["truncated"]]
    assert len(cut) == 3


async def test_model_errors_end_in_a_lapse_and_the_runtime_lives_on(directory):
    model = ScriptedModel(
        LLMBusyError("no reply in time"),
        LLMCallError("APIConnectionError: Connection error."),
        LLMBusyError("no reply in time"),
        reply("Back."),
    )
    port = FakePort()
    port.deliver("Your alarm rings.")
    config = RuntimeConfig(model_attempts=3, retry_wait=0.001)
    async with running(Runtime(directory, port, model, config)):
        await settle(port)
        (lapse,) = [r for r in trace(directory) if r["kind"] == "lapse"]
        assert len(lapse["errors"]) == 3 and lapse["purpose"] == "step"
        port.deliver("Ben says hi.")
        await settle(port)
        assert context(directory)[-1] == Message(role="assistant", content="Back.")


async def test_lapses_in_a_row_end_the_runtime_and_each_is_logged(directory, caplog):
    down = LLMCallError("APIConnectionError: Connection error.")
    model = ScriptedModel(down, reply("Back."), down, down, down)
    port = FakePort()
    port.deliver("Your alarm rings.")
    config = RuntimeConfig(model_attempts=1, max_consecutive_lapses=3)
    task = asyncio.create_task(Runtime(directory, port, model, config).run())
    for _ in range(4):  # a lapse, a reply, then three lapses in a row
        await settle(port)
        port.deliver("Ben says hi.")
    with pytest.raises(RuntimeError, match="3 requests in a row lapsed"):
        await asyncio.wait_for(task, 5)
    assert len([r for r in trace(directory) if r["kind"] == "lapse"]) == 4
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 4
    assert all(str(directory.root) in w and "Connection error" in w for w in warnings)


async def test_any_other_error_in_a_step_ends_the_runtime(directory):
    model = ScriptedModel(reply("Hm."))  # the script has no reply left for the second step
    port = FakePort()
    port.deliver("Your alarm rings.")
    runtime = Runtime(directory, port, model)
    task = asyncio.create_task(runtime.run())
    await settle(port)
    port.deliver("Ben says hi.")
    with pytest.raises(LookupError, match="no reply left"):
        await asyncio.wait_for(task, 5)
    assert not [r for r in trace(directory) if r["kind"] == "lapse"]
    assert port.busy[-1] is False


async def test_a_call_is_never_in_the_session_without_its_result(directory):
    calls = 0

    def pending_fails_on_the_second_call(args):
        nonlocal calls
        calls += 1
        if calls == 2:
            port.pending = broken
        return ToolResult("A quiet street.")

    def broken():
        raise OSError("the inbox is gone")

    port = FakePort(tools=[LOOK], results={"look_around": pending_fails_on_the_second_call})
    model = ScriptedModel(
        reply("", tool_call("look_around")),
        reply("", tool_call("look_around"), tool_call("look_around")),
    )
    port.deliver("Your alarm rings.")
    with pytest.raises(OSError, match="the inbox is gone"):
        await asyncio.wait_for(Runtime(directory, port, model).run(), 5)
    roles = [m.role for m in context(directory)]
    assert roles == ["user", "assistant", "tool"]  # the second reply and its calls are not kept


async def test_the_context_is_compacted_past_the_threshold_keeping_call_and_result(directory):
    port = FakePort(tools=[LOOK], results={"look_around": ToolResult("A quiet street.")})
    model = ScriptedModel(
        reply("", tool_call("look_around"), prompt_tokens=1_000),
        reply("", tool_call("look_around"), prompt_tokens=95_000),
        reply("## What I am doing and where I stand\nLooking around."),
        reply("Enough.", prompt_tokens=2_000),
    )
    port.deliver("Your alarm rings.")
    config = RuntimeConfig(compaction_threshold=90_000, kept_exchanges=1)
    async with running(Runtime(directory, port, model, config)):
        await settle(port)

    before, summarizing, after = model.requests[1:]
    assert summarizing.messages[-1] == INSTRUCTION
    assert summarizing.messages[: len(before.messages)] == before.messages
    assert before.tools and summarizing.tools == () and summarizing.tool_choice is None
    requests = [r for r in trace(directory) if r["kind"] == "request"]
    assert [r["tools"] == [] for r in requests] == [False, False, True, False]
    assert requests[2]["purpose"] == "compaction"
    assert [m.role for m in after.messages] == ["system", "user", "assistant", "tool"]
    assert after.messages[1].content == texts.SUMMARY.format(
        summary="## What I am doing and where I stand\nLooking around."
    )
    assert after.messages[2].tool_calls[0].id == after.messages[3].tool_call_id
    (compaction,) = [r for r in trace(directory) if r["kind"] == "compaction"]
    assert compaction["replaced"] == [1, 2, 3] and compaction["kept"] == [4, 5]
    assert [m.role for m in context(directory)] == ["user", "assistant", "tool", "assistant"]


async def test_the_resident_can_compact_on_its_own(directory):
    port = FakePort(tools=[LOOK], results={"look_around": ToolResult("A quiet street.")})
    compact = tool_call("compact")
    model = ScriptedModel(
        reply("", tool_call("look_around")), reply("", compact), reply("I woke."), reply("Fresh.")
    )
    port.deliver("Your alarm rings.")
    async with running(Runtime(directory, port, model, RuntimeConfig(kept_exchanges=1))):
        await settle(port)

    assert model.requests[2].messages[-1] == INSTRUCTION
    after = model.requests[3].messages
    assert [m.role for m in after] == ["system", "user", "assistant", "tool"]
    assert after[2].tool_calls == (compact,) and after[3].content == texts.CONDENSING


async def test_cancelling_mid_request_stops_cleanly(directory):
    model = ScriptedModel(reply(" ".join(["word"] * 500)), delay=0.01)
    port = FakePort()
    port.deliver("Your alarm rings.")
    task = asyncio.create_task(Runtime(directory, port, model).run())
    while not model.requests:
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert task.cancelled() and port.busy[-1] is False
    assert [r["kind"] for r in trace(directory)][-1] == "request"


async def test_the_resident_stays_busy_through_failed_attempts_and_waits(directory):
    port = FakePort()
    model = ScriptedModel(LLMBusyError("down"), LLMBusyError("down"), reply("Back."))
    port.deliver("Your alarm rings.")
    config = RuntimeConfig(model_attempts=3, retry_wait=0.001)
    async with running(Runtime(directory, port, model, config)):
        await settle(port)
        busy = list(port.busy)

    assert busy == [True, False]


async def test_the_resident_stays_busy_until_the_lapse_is_over(directory):
    port = FakePort()
    model = ScriptedModel(LLMBusyError("down"), LLMBusyError("down"))
    port.deliver("Your alarm rings.")
    config = RuntimeConfig(model_attempts=2, retry_wait=0.001)
    async with running(Runtime(directory, port, model, config)):
        await settle(port)
        busy = list(port.busy)

    assert busy == [True, False]
    assert [r["kind"] for r in trace(directory)][-1] == "lapse"
