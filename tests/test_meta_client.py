"""Meta client tests. Everything uses a fake client, never the network."""

import json
import types
from pathlib import Path

import httpx
import openai
import pytest

from app.config import Settings
from app.meta_client import (
    BudgetExceeded,
    MetaClient,
    MetaError,
    SpendCounter,
    asr_cost,
    sam_cost,
    token_cost,
)

REQ = httpx.Request("POST", "https://api.meta.ai/v1/responses")


def status_error(status: int, headers: dict | None = None):
    response = httpx.Response(status, headers=headers or {}, request=REQ)
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls(f"status {status}", response=response, body=None)


def make_settings(data_dir: Path, budget_usd: float = 120.0) -> Settings:
    return Settings(
        model_api_key="test-key",
        data_dir=data_dir,
        budget_usd=budget_usd,
    )


def make_response(input_tokens=1_000_000, cached_tokens=200_000, output_tokens=100_000):
    return types.SimpleNamespace(
        usage=types.SimpleNamespace(
            input_tokens=input_tokens,
            input_tokens_details=types.SimpleNamespace(cached_tokens=cached_tokens),
            output_tokens=output_tokens,
        )
    )


class FakeResponses:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, results):
        self.responses = FakeResponses(results)


def test_token_cost_spark():
    assert token_cost("muse-spark-1.3", 1_000_000, 200_000, 100_000) == pytest.approx(1.455)


def test_sam_cost():
    assert sam_cost(images=10) == pytest.approx(0.025)
    assert sam_cost(video_frames=1000) == pytest.approx(0.20)


def test_asr_cost():
    assert asr_cost(3600) == pytest.approx(0.18)
    assert asr_cost(1.2) == asr_cost(2)


def test_respond_records_spend(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([make_response()])
    sleeps: list[float] = []
    client = MetaClient(settings, client=fake, sleep=sleeps.append)

    result = client.respond(model="muse-spark-1.3", input="hello")

    assert result.usage.output_tokens == 100_000
    assert fake.responses.calls == 1
    assert sleeps == []
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["calls"] == 1
    assert data["total_usd"] == pytest.approx(1.455)
    assert data["by_model"]["muse-spark-1.3"] == pytest.approx(1.455)


def test_spend_counter_survives_restart(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([make_response()])
    MetaClient(settings, client=fake, sleep=lambda _: None).respond(
        model="muse-spark-1.3", input="hello"
    )
    first_total = SpendCounter(tmp_path / "spend.json", 120.0).total()
    second_total = SpendCounter(tmp_path / "spend.json", 120.0).total()
    assert first_total == pytest.approx(1.455)
    assert second_total == pytest.approx(first_total)


def test_budget_exceeded_does_not_call(tmp_path):
    settings = make_settings(tmp_path, budget_usd=1.0)
    spend = SpendCounter(tmp_path / "spend.json", 1.0)
    spend.add("muse-spark-1.3", 1.0)
    fake = FakeClient([make_response()])
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    with pytest.raises(BudgetExceeded):
        client.respond(model="muse-spark-1.3", input="hello")
    assert fake.responses.calls == 0


def test_rate_limit_retry_after_then_success(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([status_error(429, {"Retry-After": "2"}), make_response()])
    sleeps: list[float] = []
    client = MetaClient(settings, client=fake, sleep=sleeps.append)
    result = client.respond(model="muse-spark-1.3", input="hello")
    assert result.usage.output_tokens == 100_000
    assert fake.responses.calls == 2
    assert sleeps == [2.0]


def test_500_four_times_raises_meta_error(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([status_error(500)] * 4)
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    with pytest.raises(MetaError):
        client.respond(model="muse-spark-1.3", input="hello")
    assert fake.responses.calls == 4


@pytest.mark.parametrize("status", [400, 504])
def test_non_retryable_single_call(tmp_path, status):
    settings = make_settings(tmp_path)
    fake = FakeClient([status_error(status)])
    sleeps: list[float] = []
    client = MetaClient(settings, client=fake, sleep=sleeps.append)
    with pytest.raises(MetaError):
        client.respond(model="muse-spark-1.3", input="hello")
    assert fake.responses.calls == 1
    assert sleeps == []


def test_timeout_then_success(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([openai.APITimeoutError(request=REQ), make_response()])
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    result = client.respond(model="muse-spark-1.3", input="hello")
    assert result.usage.output_tokens == 100_000
    assert fake.responses.calls == 2


def test_respond_validation(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([make_response(), make_response()])
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    with pytest.raises(ValueError):
        client.respond(model="muse-spark-1.3", input="hello", max_output_tokens=1000)
    with pytest.raises(ValueError):
        client.respond(model="nope-1.0", input="hello")
    assert fake.responses.calls == 0


@pytest.mark.parametrize("model", ["sam-3.1", "muse-image-1.0"])
def test_respond_rejects_non_token_model(tmp_path, model):
    settings = make_settings(tmp_path)
    fake = FakeClient([make_response()])
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    with pytest.raises(ValueError):
        client.respond(model=model, input="hello")
    assert fake.responses.calls == 0


def test_respond_without_usage_not_counted(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([types.SimpleNamespace(usage=None)])
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    result = client.respond(model="muse-spark-1.3", input="hello")
    assert result.usage is None
    assert fake.responses.calls == 1
    assert not (tmp_path / "spend.json").exists()


class FakeFiles:
    """Fake for `client.files`, mirroring FakeResponses above."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.read_sizes: list[int] = []

    def create(self, **kwargs):
        self.calls += 1
        self.read_sizes.append(len(kwargs["file"].read()))
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def delete(self, file_id):
        self.calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_file_client(results):
    return types.SimpleNamespace(files=FakeFiles(results))


def test_upload_file_returns_id(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video-bytes")
    fake = make_file_client([types.SimpleNamespace(id="file-abc")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)
    assert client.upload_file(video) == "file-abc"
    assert fake.files.calls == 1


def test_upload_file_rejects_mov(tmp_path):
    video = tmp_path / "clip.mov"
    video.write_bytes(b"fake-video-bytes")
    fake = make_file_client([types.SimpleNamespace(id="file-abc")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)
    with pytest.raises(ValueError):
        client.upload_file(video)
    assert fake.files.calls == 0


def test_upload_file_retry_rereads_file(tmp_path):
    video = tmp_path / "clip.mp4"
    data = b"fake-video-bytes"
    video.write_bytes(data)
    fake = make_file_client([status_error(503), types.SimpleNamespace(id="file-abc")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)
    assert client.upload_file(video) == "file-abc"
    assert fake.files.calls == 2
    assert fake.files.read_sizes == [len(data), len(data)]


def test_delete_file_ignores_404(tmp_path):
    fake = make_file_client([status_error(404)])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)
    client.delete_file("file-missing")
    assert fake.files.calls == 1
