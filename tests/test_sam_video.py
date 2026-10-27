"""SAM 3.1 video tracking tests. Everything uses a fake client, never the network."""

import json
import types
from pathlib import Path

import httpx
import numpy as np
import openai
import pytest

from app import meta_client
from app.config import Settings
from app.meta_client import (
    BudgetExceeded,
    FrameTrack,
    MetaClient,
    MetaError,
    SpendCounter,
    TrackedObject,
    sam_cost,
)

REQ = httpx.Request("POST", "https://api.meta.ai/v1/responses")


def status_error(status):
    response = httpx.Response(status, headers={}, request=REQ)
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls(f"status {status}", response=response, body=None)


def make_settings(data_dir: Path, budget_usd: float = 120.0) -> Settings:
    return Settings(
        model_api_key="test-key",
        data_dir=data_dir,
        budget_usd=budget_usd,
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


class FakeFiles:
    def __init__(self, results):
        self.results = list(results)
        self.create_calls = 0
        self.deleted: list[str] = []

    def create(self, **kwargs):
        self.create_calls += 1
        kwargs["file"].read()
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def delete(self, file_id):
        self.deleted.append(file_id)
        return types.SimpleNamespace(deleted=True)


class FakeSamClient:
    def __init__(self, results):
        self.responses = FakeResponses(results)
        self.files = FakeFiles([types.SimpleNamespace(id="file-1")])


def _video_record(obj_id, x1, y1, x2, y2, frame_w, frame_h, confidence=None):
    from meta_sam_parser._mask_codec import _encode_raster

    mw, mh = x2 - x1 + 1, y2 - y1 + 1
    payload = _encode_raster([1] * (mw * mh), mw, mh)
    box = f"{obj_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={frame_w};h={frame_h}"
    if confidence is not None:
        box += f";c={confidence}"
    return box + "|>" + f"<|mask;x=0;y=0;data={mh},{mw},{payload}|>"


def _three_frame_answer():
    rec_a = _video_record(0, 10, 20, 13, 22, 100, 80, confidence=0.9)
    rec_b = _video_record(1, 50, 50, 59, 59, 100, 80, confidence=0.7)
    return "\n".join(
        [
            f"<0f>{rec_a},{rec_b}",
            f"<1f>{_video_record(0, 12, 20, 15, 22, 100, 80, confidence=0.8)}",
            # Frame 2 has nothing, so it emits no line and is simply absent.
            f"<3f>{_video_record(0, 14, 20, 17, 22, 100, 80)},{rec_b}",
        ]
    )


def _video_response(text):
    return types.SimpleNamespace(output_text=text, usage=None)


def _clip(tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video-bytes")
    return video


def _make_client(tmp_path: Path, fake, budget_usd: float = 120.0) -> MetaClient:
    return MetaClient(make_settings(tmp_path, budget_usd), client=fake, sleep=lambda _: None)


def _patch_frames(monkeypatch, count: int) -> None:
    monkeypatch.setattr(meta_client, "_video_frame_count", lambda path: count)


def _spend_total(tmp_path: Path) -> dict:
    with open(tmp_path / "spend.json", encoding="utf-8") as f:
        return json.load(f)


def test_segment_video_parses_frames_in_order(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 3)
    fake = FakeSamClient([_video_response(_three_frame_answer())])
    client = _make_client(tmp_path, fake)

    tracks = client.segment_video(_clip(tmp_path), "screw")

    assert [t.frame for t in tracks] == [0, 1, 3]
    assert all(isinstance(t, FrameTrack) for t in tracks)
    assert [(t.width, t.height) for t in tracks] == [(100, 80)] * 3
    assert [[o.object_id for o in t.objects] for t in tracks] == [[0, 1], [0], [0, 1]]
    first = tracks[0].objects[0]
    assert isinstance(first, TrackedObject)
    assert first.box == (10.0, 20.0, 14.0, 23.0)
    assert first.confidence == pytest.approx(0.9)
    assert first.mask is not None
    assert first.mask.dtype == np.dtype(bool)
    assert first.mask.shape == (3, 4)
    assert first.mask.all()
    assert isinstance(first.svg_path, str) and first.svg_path
    assert tracks[1].objects[0].object_id == 0
    assert tracks[1].objects[0].box == (12.0, 20.0, 16.0, 23.0)
    assert tracks[1].objects[0].confidence == pytest.approx(0.8)
    assert tracks[2].objects[0].confidence is None


def test_segment_video_request_shape_and_minimum_spend(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 3)
    fake = FakeSamClient([_video_response(_three_frame_answer())])
    client = _make_client(tmp_path, fake)

    client.segment_video(_clip(tmp_path), "screw")

    assert fake.files.create_calls == 1
    assert fake.files.deleted == ["file-1"]
    assert fake.responses.calls == 1
    kwargs = fake.responses.kwargs[0]
    assert kwargs["model"] == "sam-3.1"
    assert kwargs["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}
    content = kwargs["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "screw"}
    assert content[1] == {"type": "input_video", "file_id": "file-1"}
    # 3 counted frames bill the 50-frame minimum.
    data = _spend_total(tmp_path)
    assert data["calls"] == 1
    assert data["total_usd"] == pytest.approx(sam_cost(video_frames=50))
    assert data["by_model"]["sam-3.1"] == pytest.approx(sam_cost(video_frames=50))


def test_segment_video_spend_scales_with_frames(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 200)
    fake = FakeSamClient([_video_response("")])
    client = _make_client(tmp_path, fake)

    assert client.segment_video(_clip(tmp_path), "screw") == []

    data = _spend_total(tmp_path)
    assert data["total_usd"] == pytest.approx(sam_cost(video_frames=200))


def test_segment_video_too_many_frames(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 601)
    fake = FakeSamClient([_video_response("")])
    client = _make_client(tmp_path, fake)

    with pytest.raises(ValueError, match="over max_frames"):
        client.segment_video(_clip(tmp_path), "screw")
    assert fake.files.create_calls == 0
    assert fake.responses.calls == 0


def test_segment_video_respects_max_frames_argument(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 100)
    fake = FakeSamClient([_video_response("")])
    client = _make_client(tmp_path, fake)

    with pytest.raises(ValueError, match="over max_frames=10"):
        client.segment_video(_clip(tmp_path), "screw", max_frames=10)
    assert fake.files.create_calls == 0
    assert fake.responses.calls == 0


def test_segment_video_budget_refused_before_call(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 3)
    SpendCounter(tmp_path / "spend.json", 1.0).add("muse-spark-1.3", 1.0)
    fake = FakeSamClient([_video_response(_three_frame_answer())])
    client = _make_client(tmp_path, fake, budget_usd=1.0)

    with pytest.raises(BudgetExceeded):
        client.segment_video(_clip(tmp_path), "screw")
    assert fake.files.create_calls == 0
    assert fake.responses.calls == 0


def test_segment_video_deletes_file_on_error(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 3)
    fake = FakeSamClient([status_error(500)] * 4)
    client = _make_client(tmp_path, fake)

    with pytest.raises(MetaError):
        client.segment_video(_clip(tmp_path), "screw")
    assert fake.responses.calls == 4
    assert fake.files.deleted == ["file-1"]
    assert not (tmp_path / "spend.json").exists()


def test_segment_video_retry_429_then_success(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 3)
    fake = FakeSamClient([status_error(429), _video_response(_three_frame_answer())])
    sleeps: list[float] = []
    client = MetaClient(make_settings(tmp_path), client=fake, sleep=sleeps.append)

    tracks = client.segment_video(_clip(tmp_path), "screw")

    assert [t.frame for t in tracks] == [0, 1, 3]
    assert fake.responses.calls == 2
    assert len(sleeps) == 1
    assert fake.files.deleted == ["file-1"]


@pytest.mark.parametrize("concept", ["", "   ", "screw, bolt", "screw;bolt", "screw+bolt"])
def test_segment_video_rejects_bad_concepts(tmp_path, monkeypatch, concept):
    _patch_frames(monkeypatch, 3)
    fake = FakeSamClient([_video_response("")])
    client = _make_client(tmp_path, fake)

    with pytest.raises(ValueError):
        client.segment_video(_clip(tmp_path), concept)
    assert fake.files.create_calls == 0
    assert fake.responses.calls == 0


def test_segment_video_invalid_mask_yields_no_raster(tmp_path, monkeypatch):
    _patch_frames(monkeypatch, 3)
    good = _video_record(0, 10, 20, 13, 22, 100, 80)
    bad = '1<|box;x1=50;y1=50;x2=59;y2=59;w=100;h=80|><|mask;x=0;y=0;data=2,2,!"|>'
    fake = FakeSamClient([_video_response(f"<0f>{good},{bad}")])
    client = _make_client(tmp_path, fake)

    (track,) = client.segment_video(_clip(tmp_path), "screw")

    assert [o.object_id for o in track.objects] == [0, 1]
    assert track.objects[1].box == (50.0, 50.0, 60.0, 60.0)
    assert track.objects[1].mask is None
    assert track.objects[1].svg_path is None


def _fake_ffprobe(monkeypatch, payload, returncode=0):
    stdout = payload if isinstance(payload, str) else json.dumps(payload)

    def _run(*args, **kwargs):
        return types.SimpleNamespace(stdout=stdout, returncode=returncode)

    monkeypatch.setattr(meta_client.subprocess, "run", _run)


def test_video_frame_count_uses_nb_read_frames(tmp_path, monkeypatch):
    payload = {"streams": [{"nb_read_frames": "175", "avg_frame_rate": "30/1"}], "format": {}}
    _fake_ffprobe(monkeypatch, payload)

    assert meta_client._video_frame_count(_clip(tmp_path)) == 175


def test_video_frame_count_falls_back_to_duration_times_fps(tmp_path, monkeypatch):
    payload = {
        "streams": [{"avg_frame_rate": "30000/1001", "duration": "10.0"}],
        "format": {"duration": "10.0"},
    }
    _fake_ffprobe(monkeypatch, payload)

    assert meta_client._video_frame_count(_clip(tmp_path)) == 300


def test_video_frame_count_failure_is_value_error(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {}, returncode=1)

    with pytest.raises(ValueError, match="cannot read video"):
        meta_client._video_frame_count(_clip(tmp_path))


def test_video_frame_count_without_timing_is_value_error(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {"streams": [{}], "format": {}})

    with pytest.raises(ValueError, match="cannot count frames"):
        meta_client._video_frame_count(_clip(tmp_path))
