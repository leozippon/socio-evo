import pytest

from agent.directory import AgentDirectory

BACKGROUND = "I am Ana Reyes, thirty-four, a programmer who moved here in spring."


@pytest.fixture
def directory(tmp_path) -> AgentDirectory:
    return AgentDirectory.create(tmp_path / "ana", background=BACKGROUND)
