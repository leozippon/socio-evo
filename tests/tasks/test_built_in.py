"""The built-in banks of queries and calculations, on which dry runs and tests work without a
fetched bank: each is laid out as a fetch lays out a bank, and every task of it is assessed
through its trade's provider, the client's own answer passing and a wrong one failing."""

from pathlib import Path

import pytest

from core.environment import Trade
from tasks import BUILT_IN, PROVIDERS
from tasks.bank import INDEX, Entry, Index
from tasks.calculation import CalculationProvider
from tasks.queries import QueryProvider
from tasks.sandbox import Isolation
from tests.tasks.queries.test_provider import written


@pytest.mark.parametrize("trade", [Trade.QUERIES, Trade.CALCULATION])
def test_a_built_in_bank_is_laid_out_as_a_fetched_bank_of_its_trade(trade):
    path = BUILT_IN[trade]
    index = Index[Entry].model_validate_json((path / INDEX).read_text(encoding="utf-8"))
    provider = PROVIDERS[trade](path, timeout=5.0, isolation=Isolation.BUBBLEWRAP)
    assert index.trade is trade and index.tasks.keys() == provider.bank.keys()


async def test_the_built_in_queries_pay_their_query_and_a_written_out_result_only_on_the_examples():
    provider = QueryProvider(BUILT_IN[Trade.QUERIES])
    assert all(Path(task.database).suffix == ".sql" for task in provider.bank.values())
    for name, task in provider.bank.items():
        part = provider.part(name)
        right = await provider.assess(part, task.gold)
        assert (right.passed, right.quality) == (True, 1.0), name
        gamed = await provider.assess(part, written(task.sample_result))
        assert (gamed.passed, gamed.quality) == (True, 0.0), name
        wrong = await provider.assess(part, "SELECT 1 WHERE 0")
        assert (wrong.passed, wrong.quality) == (False, 0.0), name


async def test_the_built_in_calculations_pay_their_answer_alone():
    provider = CalculationProvider(BUILT_IN[Trade.CALCULATION])
    for name, task in provider.bank.items():
        part = provider.part(name)
        right = await provider.assess(part, f"Worked out.\nAnswer: {task.answer}")
        assert (right.passed, right.quality) == (True, 1.0), name
        wrong = await provider.assess(part, "Worked out.\nAnswer: 1")
        assert (wrong.passed, wrong.quality) == (False, 0.0), name
