import pytest


@pytest.fixture(autouse=True)
def disable_live_pricing(monkeypatch):
    monkeypatch.setenv("ENABLE_LIVE_PRICING", "false")
