"""Safety net for every test: no network, so no test can ever spend Meta credits."""

import httpx
import pytest

from app import meta_client
from app.limits import LIMITER


def _no_network(*args, **kwargs):
    raise RuntimeError("network is disabled in tests: use a fake client")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", _no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", _no_network)
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("PIPELINE_WORKERS", "1")  # fake clients answer in order
    monkeypatch.setattr(meta_client, "_factory", None)  # each test starts with no fake leaked
    LIMITER.reset()  # per-visitor counts never leak from one test to the next
