"""Safety net for every test: no network, so no test can ever spend Meta credits."""

import httpx
import pytest


def _no_network(*args, **kwargs):
    raise RuntimeError("network is disabled in tests: use a fake client")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", _no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", _no_network)
    monkeypatch.setenv("MODEL_API_KEY", "")
