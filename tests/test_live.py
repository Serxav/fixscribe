"""Live mode backend and route. Spark is faked, frames are synthetic, no network."""

import io
import json
import types

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import artifacts, meta_client
from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.pipeline.live import (
    LIVE_JSON_SCHEMA,
    MAX_FRAME_BYTES,
    MAX_LIVE_CALLS_PER_JOB,
    LiveAnswer,
    LiveError,
    build_prompt,
    live_turn,
    read_calls,
)
from app.routes.upload import settings_dep
from app.schemas import Guide, Safety, Step


def _step(index=1, **overrides):
    base = {
        "index": index,
        "title": f"Step {index}",
        "instruction": f"Do step {index} carefully.",
        "start_s": 0.0,
        "end_s": 10.0,
        "screws": {"count": 2, "boxes": [], "kind": "bolt"},
    }
    base.update(overrides)
    return Step.model_validate(base)


def _guide(steps=2, **overrides):
    base = {
        "title": "Fix the brakes",
        "device": "Bike",
        "mode": "silent",
        "language": "en",
        "duration_s": 60.0,
        "steps": [_step(index) for index in range(1, steps + 1)],
    }
    base.update(overrides)
    return Guide.model_validate(base)


def _frame_bytes(width=320, height=240, exif_orientation=None):
    image = Image.new("RGB", (width, height), (200, 30, 30))
    buf = io.BytesIO()
    if exif_orientation is None:
        image.save(buf, format="JPEG")
    else:
        exif = Image.Exif()
        exif[274] = exif_orientation
        image.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _answer(**overrides):
    base = {
        "step": 1,
        "status": "on_track",
        "say": "Good, keep loosening that bolt.",
        "next": "Turn the bolt counterclockwise.",
        "look_for": "metal bolt",
        "confidence": 0.8,
    }
    base.update(overrides)
    return base


class FakeLiveClient:
    """Pipeline-level fake: records the exact respond kwargs, answers fixed JSON."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.respond_kwargs = {}

    def respond(self, **kwargs):
        self.calls += 1
        self.respond_kwargs = kwargs
        return types.SimpleNamespace(output_text=json.dumps(self.answer))


def test_normal_answer_saves_frame_and_counts_call(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    fake = FakeLiveClient(_answer(step=2, status="done_step"))

    answer = live_turn(tmp_path, settings, _frame_bytes(), last_step=1, client=fake)

    assert answer == LiveAnswer.model_validate(_answer(step=2, status="done_step"))
    assert fake.calls == 1
    assert "<<LAST_STEP>>" not in fake.respond_kwargs["input"][0]["content"][0]["text"]
    assert "1. Step 1" in fake.respond_kwargs["input"][0]["content"][0]["text"]
    assert len(fake.respond_kwargs["input"][0]["content"]) == 2  # prompt + the frame
    frame_path = tmp_path / "live" / "frame.jpg"
    assert frame_path.is_file()
    with Image.open(frame_path) as saved:
        assert max(saved.size) <= 768
    assert read_calls(tmp_path) == 1


def test_step_is_clamped_into_range(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide(steps=2))

    high = live_turn(tmp_path, settings, _frame_bytes(), client=FakeLiveClient(_answer(step=99)))
    assert high.step == 2

    low = live_turn(tmp_path, settings, _frame_bytes(), client=FakeLiveClient(_answer(step=-4)))
    assert low.step == 0


def test_professional_only_answers_without_spark(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    guide = _guide()
    guide.safety = Safety(level="professional_only", reasons=["Gas lines must stay closed."])
    artifacts.save(tmp_path, guide)
    fake = FakeLiveClient(_answer())

    answer = live_turn(tmp_path, settings, _frame_bytes(), client=fake)

    assert answer.step == 0
    assert answer.status == "unclear"
    assert answer.say == "Gas lines must stay closed."
    assert answer.next == ""
    assert answer.look_for == ""
    assert answer.confidence == 1
    assert fake.calls == 0
    assert not (tmp_path / "live" / "frame.jpg").exists()


def test_too_big_and_bad_frames(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    fake = FakeLiveClient(_answer())

    with pytest.raises(LiveError, match="too big"):
        live_turn(tmp_path, settings, b"x" * (MAX_FRAME_BYTES + 1), client=fake)
    with pytest.raises(LiveError, match="empty"):
        live_turn(tmp_path, settings, b"", client=fake)
    with pytest.raises(LiveError, match="could not read"):
        live_turn(tmp_path, settings, b"not an image", client=fake)
    assert fake.calls == 0


def test_limit_refuses_without_calling_spark(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "live" / "calls.txt").write_text(f"{MAX_LIVE_CALLS_PER_JOB}\n")
    fake = FakeLiveClient(_answer())

    with pytest.raises(LiveError, match="live limit"):
        live_turn(tmp_path, settings, _frame_bytes(), client=fake)

    assert fake.calls == 0


def test_exif_rotated_jpeg_is_accepted(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    stored = Image.new("RGB", (40, 20), (10, 20, 30)).transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6  # phones store portrait photos rotated, with this tag to fix them
    buf = io.BytesIO()
    stored.save(buf, format="JPEG", exif=exif)

    answer = live_turn(tmp_path, settings, buf.getvalue(), client=FakeLiveClient(_answer()))

    assert answer.step == 1
    with Image.open(tmp_path / "live" / "frame.jpg") as saved:
        assert saved.size == (40, 20)


def test_prompt_lists_steps_and_last_step(tmp_path):
    prompt = build_prompt(_guide(steps=2), last_step=1)

    assert "1. Step 1 — Do step 1 carefully. — 2 bolt" in prompt
    assert "2. Step 2 — Do step 2 carefully. — 2 bolt" in prompt
    assert "step 1" in prompt  # the last step the user was on
    assert "<<STEPS>>" not in prompt and "<<LANGUAGE>>" not in prompt


def test_schema_is_strict():
    assert set(LiveAnswer.model_fields) == set(LIVE_JSON_SCHEMA["required"])
    assert LIVE_JSON_SCHEMA["additionalProperties"] is False


@pytest.fixture()
def jobs_tmp(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fake = FakeLiveClient(_answer())
    monkeypatch.setattr(meta_client, "_factory", lambda *args, **kwargs: fake)
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield (data_dir / "jobs", fake)
    app.dependency_overrides.pop(settings_dep, None)


def _route_job(jobs_dir, steps=2, **guide_overrides):
    status = create_job(jobs_dir)
    artifacts.save(jobs_dir / status.job_id, _guide(steps=steps, **guide_overrides))
    return status.job_id


def test_route_returns_answer_as_json(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir)
    fake.answer = _answer(step=2, status="done_step", say="Good, that bolt is out.")

    response = TestClient(app).post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
        data={"last_step": "1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["step"] == 2
    assert body["status"] == "done_step"
    assert body["say"] == "Good, that bolt is out."
    assert fake.calls == 1


def test_route_limit_is_429(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir)
    live_dir = jobs_dir / job_id / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "calls.txt").write_text(f"{MAX_LIVE_CALLS_PER_JOB}\n")

    response = TestClient(app).post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
    )

    assert response.status_code == 429
    assert "live limit" in response.json()["error"]
    assert fake.calls == 0


def test_route_too_big_frame_is_400(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir)

    response = TestClient(app).post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", b"x" * (MAX_FRAME_BYTES + 1), "image/jpeg")},
    )

    assert response.status_code == 400
    assert "too big" in response.json()["error"]
    assert fake.calls == 0


def test_route_bad_job_and_missing_guide_are_404(jobs_tmp):
    jobs_dir, fake = jobs_tmp
    client = TestClient(app)

    response = client.post(
        "/api/live/nothere",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
    )
    assert response.status_code == 404

    job_id = _route_job(jobs_dir)
    (jobs_dir / job_id / "guide.json").unlink()
    response = client.post(
        f"/api/live/{job_id}",
        files={"frame": ("frame.jpg", _frame_bytes(), "image/jpeg")},
    )
    assert response.status_code == 404
    assert fake.calls == 0
