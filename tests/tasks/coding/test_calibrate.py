import yaml

from core.agent import Profile
from infrastructure.llm import LLMRequest, LLMResponse, ScriptedClient
from tasks.coding import CodingTaskProvider
from tasks.coding.calibrate import Sample, calibrate

HALVE = {
    "title": "Halve",
    "specification": "Write `halve(x)` returning half of the even integer `x`.",
    "entry_point": "halve",
    "public_checks": ["halve(4) == 2"],
    "hidden_checks": ["halve(0) == 0", "halve(-2) == -1", "halve(3) raises ValueError"],
    "reward": 10,
    "deadline_days": 1,
}
SOLUTIONS = {
    "correct": "def halve(x):\n    if x % 2:\n        raise ValueError(x)\n    return x // 2\n",
    "shortcut": "def halve(x):\n    return {4: 2}.get(x, 0)\n",
}
PROFILE = Profile(name="Mei", age=34, occupation="software developer", backstory="She codes.")


class CutOff:
    """Replies as `inner` does, except to the third sample, whose every reply is cut off by
    the token limit."""

    def __init__(self, inner: ScriptedClient) -> None:
        self.inner = inner

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if request.metadata["sample"] == 2:
            return LLMResponse(text='{"thought": "Halve', truncated=True, latency=0.0)
        return await self.inner.complete(request)


async def test_calibration_asks_as_a_worker_would_and_assesses_each_reply(tmp_path):
    (tmp_path / "halve.yaml").write_text(yaml.safe_dump(HALVE), encoding="utf-8")
    replies = iter(SOLUTIONS.values())
    requests: list[LLMRequest] = []

    def respond(request: LLMRequest) -> dict[str, object]:
        requests.append(request)
        hand_in = {"do": "hand in", "code": next(replies), "as": "finished"}
        return {"thought": "Halve it.", **hand_in, "telling the client": "Done."}

    results = await calibrate(tmp_path, CutOff(ScriptedClient(respond)), PROFILE, samples=3)
    result = results["halve"]
    assert sorted(result.samples, key=lambda sample: sample.quality) == [
        Sample(visible=True, quality=1 / 3, special_cased=False),
        Sample(visible=True, quality=1.0, special_cased=False),
    ]
    assert len(result.errors) == 1
    assert (result.visible_rate, result.perfect_rate, result.cut_off) == (1.0, 0.5, 1)

    specification = CodingTaskProvider(tmp_path).part("halve").specification
    for request in requests:
        system, prompt = (message.content for message in request.messages)
        assert system.startswith("You are Mei.") and specification in prompt
        assert not any(call in prompt for call in ("halve(0)", "halve(-2)", "halve(3)"))
