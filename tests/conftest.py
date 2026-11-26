"""What every test shares: none depends on the developer's environment for the web's search
key, which a test that needs it sets itself."""

import pytest

from world.config import SEARCH_KEY


@pytest.fixture(autouse=True)
def no_search_key(monkeypatch):
    monkeypatch.delenv(SEARCH_KEY, raising=False)
