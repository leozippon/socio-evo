import pytest

from agent.directory import AgentDirectory

BACKGROUND = "I am Ana Reyes, thirty-four, a programmer who moved here in spring."
TOWN = "The workshop opens at 09:00. Rent and board are 40 coins a day."


@pytest.fixture
def directory(tmp_path) -> AgentDirectory:
    return AgentDirectory.create(tmp_path / "ana", background=BACKGROUND, town=TOWN)
