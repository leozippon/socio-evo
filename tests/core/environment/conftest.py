"""The environment of the environment tests: a town of four residents with one work place and
one café, built on the stand-in provider of `test_environment`."""

import pytest

from core.environment import Environment
from tests.core.environment.test_environment import AGENTS, CROWNS, Provider, make_config


@pytest.fixture
def make_env(tmp_path):
    made = iter(range(100))

    def make(circumstances=None, setting=CROWNS, **conditions) -> Environment:
        config = make_config(circumstances, setting, **conditions)
        path = tmp_path / f"events-{next(made)}.jsonl"
        return Environment.create(config, AGENTS, Provider(), path)

    return make


@pytest.fixture
def env(make_env) -> Environment:
    return make_env()
