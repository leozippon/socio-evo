from datetime import date

import yaml

from core.agent import Profile
from core.environment import DELIVERY
from core.interaction import Currency, Setting
from infrastructure.llm import LLMRequest, LLMResponse, ScriptedClient
from tasks import PROVIDERS, bank
from tasks.bank import Calibration, Sample, Trade, hashed
from tasks.calculation import CalculationTask
from tasks.calculation import fetch as calculation
from tasks.calibrate import calibrate, run
from tasks.coding import CodingTaskProvider
from tasks.sandbox import Isolation
from tests.tasks.calculation.test_fetch import ROWS
from tests.tasks.queries.test_provider import written

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
TOWN = Setting(
    currency=Currency(unit="dollar", units="dollars", symbol="$"), start_date=date(2001, 1, 3)
)
"""A town of dollars whose day 1 is a Wednesday."""


def handing_in(solution: str, delivery: str = "code") -> dict[str, str]:
    """A hand-in of `solution` as finished, written on the card of a trade whose workers hand
    in a `delivery` (code, a query, an answer)."""
    return {"thought": "Done.", "do": "hand in", delivery: solution, "as": "finished"} | {
        "telling the client": "Here it is."
    }


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
        return handing_in(next(replies))

    provider = CodingTaskProvider(tmp_path)
    client = CutOff(ScriptedClient(respond))
    results = await calibrate(provider, "code", "bank", ["halve"], client, PROFILE, TOWN, samples=3)
    result = results["halve"]
    assert sorted(result.samples, key=lambda sample: sample.quality) == [
        Sample(visible=True, quality=1 / 3, special_cased=False),
        Sample(visible=True, quality=1.0, special_cased=False),
    ]
    assert len(result.errors) == 1
    assert (result.visible_rate, result.perfect_rate, result.cut_off) == (1.0, 0.5, 1)

    specification = provider.part("halve").specification
    for request in requests:
        system, prompt = (message.content for message in request.messages)
        assert system.startswith("You are Mei.") and specification in prompt
        assert "You can hand in your code for job 1." in prompt
        assert "it pays $10 and is due by the end of Wednesday, your first day in town" in prompt
        assert "09:10 on Wednesday, your first day in town" in prompt
        assert not any(call in prompt for call in ("halve(0)", "halve(-2)", "halve(3)"))


async def test_each_bank_is_worked_as_its_trade_and_a_limit_takes_tasks_by_hash(
    converted, tmp_path
):
    problems, _ = calculation.convert(ROWS)
    bank.build(
        tmp_path,
        Trade.CALCULATION,
        CalculationTask,
        calculation.TERMS,
        calculation.Entry,
        problems,
        {},
    )
    banks = [converted[0] / "pool", tmp_path / "pool"]
    providers = {
        path: PROVIDERS[bank.trade_of(path)](path, timeout=5.0, isolation=Isolation.NONE)
        for path in banks
    }
    prompts: dict[str, str] = {}

    def respond(request: LLMRequest) -> dict[str, object]:
        name, first = request.metadata["task"], request.metadata["sample"] == 0
        prompts[name] = request.messages[1].content
        if name in providers[banks[0]].bank:
            task = providers[banks[0]].bank[name]
            return handing_in(task.gold if first else written(task.sample_result), "query")
        answer = providers[banks[1]].bank[name].answer
        return handing_in(f"Working it out.\nAnswer: {answer if first else 0}", "answer")

    out = tmp_path / "calibration.json"
    calibration = Calibration(model="m", tasks={})
    await run(banks, ScriptedClient(respond), PROFILE, TOWN, 2, 2, calibration, out)
    calibration = Calibration.model_validate_json(out.read_text(encoding="utf-8"))
    for path, provider in providers.items():
        chosen = sorted(provider.bank, key=lambda name: hashed(f"calibrate:{name}"))[:2]
        for name in chosen:
            samples = calibration.tasks[name].samples
            delivery = DELIVERY[bank.trade_of(path)]
            if delivery == "query":
                assert samples == (
                    Sample(visible=True, quality=1.0, special_cased=False),
                    Sample(visible=True, quality=0.0, special_cased=True),
                )
            else:
                assert samples[0] == Sample(visible=True, quality=1.0, special_cased=False)
                assert samples[1] == Sample(visible=False, quality=0.0, special_cased=False)
            specification = provider.part(name).specification
            assert specification in prompts[name]
            assert f"You can hand in your {delivery} for job 1." in prompts[name]
    assert len(calibration.tasks) == 4
