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
    Detection,
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
        self.kwargs: list[dict] = []

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
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


def make_wav(path: Path, seconds: float = 1.0) -> Path:
    import wave

    frames = int(24000 * seconds)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\0" * frames * 2)
    return path


ASR_PAYLOAD = {
    "sessionId": "sess-1",
    "transcript": "Step one remove the two screws now",
    "audioDurationMs": 42500,
    "turns": [{"turnId": 1, "startMs": 1200, "endMs": 3400, "transcript": "Step one"}],
}


class FakeHttp:
    """Fake httpx client: post returns canned responses or raises."""

    def __init__(self, results):
        self.results = list(results)
        self.posts: list = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item
        request = httpx.Request("POST", url)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, request=request)
        return httpx.Response(status, json=payload, request=request)


def make_asr_client(tmp_path, results, **kwargs):
    settings = make_settings(tmp_path, **kwargs)
    fake_http = FakeHttp(results)
    client = MetaClient(settings, sleep=lambda _: None, http=fake_http)
    return client, fake_http


def test_transcribe_success_posts_multipart_and_records_spend(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    client, fake_http = make_asr_client(tmp_path, [(200, ASR_PAYLOAD)])

    result = client.transcribe(wav, language_bias=["Spanish", "English"], keywords=["step", "paso"])

    assert result["sessionId"] == "sess-1"
    assert len(fake_http.posts) == 1
    url, kwargs = fake_http.posts[0]
    assert url.endswith("/asr/transcribe")
    assert kwargs["headers"]["Accept"] == "application/json"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    request_part = json.loads(kwargs["files"]["request"][1])
    assert request_part == {
        "model": "muse-voice-transcribe-1.0",
        "audioEncoding": "WAV",
        "mode": "ENDPOINTING",
        "languageBias": ["Spanish", "English"],
        "keywords": ["step", "paso"],
    }
    assert kwargs["files"]["request"][2] == "application/json"
    assert kwargs["files"]["audio"][0] == "audio.wav"
    assert kwargs["files"]["audio"][2] == "audio/wav"
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["calls"] == 1
    assert data["total_usd"] == pytest.approx(asr_cost(42.5))
    assert data["by_model"]["muse-voice-transcribe-1.0"] == pytest.approx(asr_cost(42.5))


def test_transcribe_429_then_success(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    client, fake_http = make_asr_client(
        tmp_path, [(429, {"error": "slow down"}), (200, ASR_PAYLOAD)]
    )
    result = client.transcribe(wav)
    assert result["sessionId"] == "sess-1"
    assert len(fake_http.posts) == 2


def test_transcribe_400_raises_meta_error(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    client, fake_http = make_asr_client(tmp_path, [(400, {"error": "bad audio"})])
    with pytest.raises(MetaError):
        client.transcribe(wav)
    assert len(fake_http.posts) == 1


def test_transcribe_read_timeout_then_success(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    url = "https://api.meta.ai/v1/asr/transcribe"
    timeout = httpx.ReadTimeout("timed out", request=httpx.Request("POST", url))
    client, fake_http = make_asr_client(tmp_path, [timeout, (200, ASR_PAYLOAD)])
    result = client.transcribe(wav)
    assert result["sessionId"] == "sess-1"
    assert len(fake_http.posts) == 2


def test_transcribe_rejects_big_file(tmp_path):
    big = tmp_path / "audio.wav"
    big.write_bytes(b"\0" * (33 * 1024 * 1024))
    client, fake_http = make_asr_client(tmp_path, [(200, ASR_PAYLOAD)])
    with pytest.raises(ValueError):
        client.transcribe(big)
    assert fake_http.posts == []


def test_transcribe_budget_exceeded_no_post(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    SpendCounter(tmp_path / "spend.json", 1.0).add("muse-spark-1.3", 1.0)
    client, fake_http = make_asr_client(tmp_path, [(200, ASR_PAYLOAD)], budget_usd=1.0)
    with pytest.raises(BudgetExceeded):
        client.transcribe(wav)
    assert fake_http.posts == []


def test_respond_timeout_s_passes_httpx_timeout(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([make_response()])
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    client.respond(model="muse-spark-1.3", input="hello", timeout_s=600)
    assert fake.responses.calls == 1
    timeout = fake.responses.kwargs[0]["timeout"]
    assert timeout.read == 600
    assert timeout.connect == 10.0


def test_respond_retry_timeouts_false_raises_once_no_sleep(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([openai.APITimeoutError(request=REQ), make_response()])
    sleeps: list[float] = []
    client = MetaClient(settings, client=fake, sleep=sleeps.append)
    with pytest.raises(MetaError, match="meta api timed out"):
        client.respond(model="muse-spark-1.3", input="hello", retry_timeouts=False)
    assert fake.responses.calls == 1
    assert sleeps == []


def test_retry_after_capped_at_30(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([status_error(429, {"Retry-After": "86400"}), make_response()])
    sleeps: list[float] = []
    client = MetaClient(settings, client=fake, sleep=sleeps.append)
    client.respond(model="muse-spark-1.3", input="hello")
    assert sleeps == [30.0]


def test_retry_after_negative_uses_fallback(tmp_path):
    settings = make_settings(tmp_path)
    fake = FakeClient([status_error(429, {"Retry-After": "-5"}), make_response()])
    sleeps: list[float] = []
    client = MetaClient(settings, client=fake, sleep=sleeps.append)
    client.respond(model="muse-spark-1.3", input="hello")
    assert len(sleeps) == 1
    assert 0 <= sleeps[0] < 2.0


def test_spend_corrupt_json_rebuilds_from_log(tmp_path):
    (tmp_path / "spend.json").write_text("{", encoding="utf-8")
    (tmp_path / "spend.log").write_text(
        '{"model": "muse-spark-1.3", "usd": 1.0, "at": "2026-10-26T00:00:00+00:00"}\n'
        "not json\n"
        '{"model": "muse-spark-1.3", "usd": 2.0, "at": "2026-10-26T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    counter = SpendCounter(tmp_path / "spend.json", 120.0)
    assert counter.total() == pytest.approx(3.0)
    with pytest.raises(BudgetExceeded):
        SpendCounter(tmp_path / "spend.json", 2.0).check()
    new_total = counter.add("muse-spark-1.3", 0.5)
    assert new_total == pytest.approx(3.5)
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_usd"] == pytest.approx(3.5)
    assert data["calls"] == 3
    assert data["by_model"]["muse-spark-1.3"] == pytest.approx(3.5)


def test_transcribe_connect_error_then_success_and_timeout(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    url = "https://api.meta.ai/v1/asr/transcribe"
    connect_error = httpx.ConnectError("refused", request=httpx.Request("POST", url))
    client, fake_http = make_asr_client(tmp_path, [connect_error, (200, ASR_PAYLOAD)])
    result = client.transcribe(wav)
    assert result["sessionId"] == "sess-1"
    assert len(fake_http.posts) == 2
    assert fake_http.posts[0][1]["timeout"].read == 300
    assert fake_http.posts[1][1]["timeout"].read == 300


def test_transcribe_missing_duration_uses_wav(tmp_path):
    wav = make_wav(tmp_path / "audio.wav", seconds=2.0)
    payload = {"sessionId": "sess-1", "transcript": "hi", "turns": []}
    client, _fake_http = make_asr_client(tmp_path, [(200, payload)])
    result = client.transcribe(wav)
    assert result["audioDurationMs"] == 2000
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_usd"] == pytest.approx(asr_cost(2))


def test_transcribe_invalid_json_records_spend(tmp_path):
    wav = make_wav(tmp_path / "audio.wav", seconds=2.0)
    client, _fake_http = make_asr_client(tmp_path, [(200, b"not json")])
    with pytest.raises(MetaError, match="asr returned an invalid answer"):
        client.transcribe(wav)
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_usd"] == pytest.approx(asr_cost(2))


def test_transcribe_non_dict_records_spend(tmp_path):
    wav = make_wav(tmp_path / "audio.wav")
    client, _fake_http = make_asr_client(tmp_path, [(200, ["not", "a", "dict"])])
    with pytest.raises(MetaError, match="asr returned an invalid answer"):
        client.transcribe(wav)
    assert (tmp_path / "spend.json").exists()


def test_transcribe_never_logs_authorization(tmp_path, caplog):
    settings = Settings(
        model_api_key="test-secret-key-xyz",
        data_dir=tmp_path,
        budget_usd=120.0,
    )
    wav = make_wav(tmp_path / "audio.wav")
    fake_http = FakeHttp([(429, {"error": "slow down"}), (200, ASR_PAYLOAD)])
    client = MetaClient(settings, sleep=lambda _: None, http=fake_http)
    with caplog.at_level("DEBUG"):
        result = client.transcribe(wav)
    assert result["sessionId"] == "sess-1"
    assert "test-secret-key-xyz" not in caplog.text
    assert ASR_PAYLOAD["transcript"] not in caplog.text


def _sam_fake_record(obj_id, x1, y1, x2, y2, img_w, img_h):
    from meta_sam_parser._mask_codec import _encode_raster

    mw, mh = x2 - x1 + 1, y2 - y1 + 1
    payload = _encode_raster([1] * (mw * mh), mw, mh)
    return (
        f"{obj_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={img_w};h={img_h}|>"
        f"<|mask;x=0;y=0;data={mh},{mw},{payload}|>"
    )


def _sam_output_text():
    return "<0f>" + ",".join(
        [
            _sam_fake_record(0, 10, 20, 13, 22, 100, 100),
            _sam_fake_record(1, 50, 50, 59, 59, 100, 100),
        ]
    )


def _write_test_image(path: Path, width: int = 100, height: int = 100) -> Path:
    import cv2
    import numpy as np

    image = np.full((height, width, 3), 120, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    return path


def _sam_response(output_text, images_processed=None):
    usage = None
    if images_processed is not None:
        usage = types.SimpleNamespace(images_processed=images_processed)
    return types.SimpleNamespace(output_text=output_text, usage=usage)


def test_segment_sends_sam_request(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response(_sam_output_text())])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    detections, size = client.segment(image_path, "screw")

    assert size == (100, 100)
    assert len(detections) == 2
    assert fake.responses.calls == 1
    kwargs = fake.responses.kwargs[0]
    assert kwargs["model"] == "sam-3.1"
    assert kwargs["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}
    message = kwargs["input"][0]
    assert message["type"] == "message"
    assert message["role"] == "user"
    content = message["content"]
    assert content[0] == {"type": "input_text", "text": "screw"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")


def test_segment_parses_two_detections_and_records_spend(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response(_sam_output_text())])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    detections, size = client.segment(image_path, "screw")

    assert size == (100, 100)
    assert [d.box for d in detections] == [(10.0, 20.0, 14.0, 23.0), (50.0, 50.0, 60.0, 60.0)]
    assert [d.object_id for d in detections] == ["0", "1"]
    assert all(isinstance(d, Detection) for d in detections)
    assert detections[0].mask is not None
    assert detections[0].mask_size == (4, 3)
    assert detections[0].mask_bounds == (10.0, 20.0, 14.0, 23.0)
    assert detections[1].mask is not None
    assert detections[1].mask_size == (10, 10)
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["calls"] == 1
    assert data["total_usd"] == pytest.approx(sam_cost(images=1))
    assert data["by_model"]["sam-3.1"] == pytest.approx(sam_cost(images=1))


def test_segment_empty_output_returns_no_detections(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response("")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    detections, size = client.segment(image_path, "screw")

    assert detections == []
    assert size == (100, 100)
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_usd"] == pytest.approx(sam_cost(images=1))


def test_segment_uses_images_processed_when_present(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response("", images_processed=3)])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    detections, _size = client.segment(image_path, "screw")

    assert detections == []
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_usd"] == pytest.approx(sam_cost(images=3))


def test_segment_resizes_large_image(tmp_path):
    image_path = _write_test_image(tmp_path / "big.jpg", width=4000, height=3000)
    fake = FakeClient([_sam_response("")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    _detections, size = client.segment(image_path, "screw")

    assert size == (1280, 960)
    assert max(size) == 1280


def test_segment_rejects_multi_concept_without_call(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response(_sam_output_text())])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    with pytest.raises(ValueError):
        client.segment(image_path, "screw, bolt")
    assert fake.responses.calls == 0


@pytest.mark.parametrize("concept", ["", "   ", "screw; bolt", "screw+bolt"])
def test_segment_rejects_bad_concepts(tmp_path, concept):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    fake = FakeClient([_sam_response("")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    with pytest.raises(ValueError):
        client.segment(image_path, concept)
    assert fake.responses.calls == 0


def test_segment_budget_exceeded_no_call(tmp_path):
    image_path = _write_test_image(tmp_path / "frame.jpg")
    SpendCounter(tmp_path / "spend.json", 1.0).add("muse-spark-1.3", 1.0)
    fake = FakeClient([_sam_response(_sam_output_text())])
    client = MetaClient(make_settings(tmp_path, budget_usd=1.0), client=fake, sleep=lambda _: None)

    with pytest.raises(BudgetExceeded):
        client.segment(image_path, "screw")
    assert fake.responses.calls == 0


def test_segment_unreadable_image_no_call(tmp_path):
    missing = tmp_path / "missing.jpg"
    fake = FakeClient([_sam_response("")])
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=lambda _: None)

    with pytest.raises(ValueError):
        client.segment(missing, "screw")
    assert fake.responses.calls == 0
