"""Tap a fastener: add one SAM follows from a tapped point, or remove a wrong marker."""

from types import SimpleNamespace

import pytest

from app import artifacts
from app.pipeline import fasteners, perception, tap
from app.schemas import Guide, Perception
from tests.test_perception import FakeMeta, _job, _step


@pytest.fixture(autouse=True)
def whole_frame(monkeypatch):
    monkeypatch.setattr(fasteners, "MIN_AREA", 1.0)


class PointSam:
    """SAM video that follows a tapped point: a small box around it on every frame."""

    def __init__(self, answer=True):
        self.answer = answer
        self.prompts = []

    def segment_video(self, clip, boxes=(), size=None):
        self.prompts = list(boxes)
        count = fasteners.frame_count(clip)
        (oid, _, (x, y)), = boxes  # fmt: skip
        objects = [SimpleNamespace(object_id=oid, box=(x - 6, y - 6, x + 6, y + 6))]
        return [
            SimpleNamespace(frame=i, width=size[0], height=size[1],
                            objects=objects if self.answer else [])
            for i in range(count)
        ]  # fmt: skip


@pytest.fixture
def job(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=4)], task="assemble")
    perception.run(tmp_path, settings, client=FakeMeta())
    from app.pipeline import publish

    publish.run(tmp_path, settings)
    return tmp_path, settings


def test_tapping_a_missing_fastener_adds_it(job):
    job_dir, settings = job
    sam = PointSam()
    result = tap.add_fastener(job_dir, settings, 1, 0.5, 0.75, client=sam)
    step = result.steps[0]
    assert len(step.removed) == 4
    assert [r.id for r in step.removed] == ["S1", "S2", "S3", "S4"]
    assert "Fastener map corrected by hand." in step.notes
    assert any(abs(r.box.x + r.box.w / 2 - 0.5) < 0.02 for r in step.removed)
    assert sam.prompts[0][2] == (640, 720)  # the tapped point (160, 180) in the 4x zoomed clip
    assert tap.taps_used(job_dir) == 1
    guide = artifacts.load(job_dir, Guide)
    assert len(guide.steps[0].screws.boxes) == 4


def test_tap_on_nothing_says_so(job):
    job_dir, settings = job
    with pytest.raises(tap.TapError, match="nothing to follow"):
        tap.add_fastener(job_dir, settings, 1, 0.5, 0.75, client=PointSam(answer=False))


def test_tap_limit(job, monkeypatch):
    job_dir, settings = job
    monkeypatch.setattr(tap, "MAX_TAPS", 0)
    with pytest.raises(tap.TapError, match="limit"):
        tap.add_fastener(job_dir, settings, 1, 0.5, 0.5, client=PointSam())


def test_removing_a_wrong_marker_needs_no_meta_call(job):
    job_dir, settings = job
    result = tap.remove_fastener(job_dir, settings, 1, 2)
    assert [r.id for r in result.steps[0].removed] == ["S1", "S2"]
    assert artifacts.load(job_dir, Perception) == result
    with pytest.raises(tap.TapError):
        tap.remove_fastener(job_dir, settings, 1, 9)


def test_steps_without_fasteners_cannot_be_tapped(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0)])
    perception.run(tmp_path, settings, client=FakeMeta())
    with pytest.raises(tap.TapError, match="no fasteners"):
        tap.add_fastener(tmp_path, settings, 1, 0.5, 0.5, client=PointSam())


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import app
    from app.routes.upload import settings_dep

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield TestClient(app), data_dir / "jobs"
    app.dependency_overrides.pop(settings_dep, None)


def _route_job(jobs_dir):
    from app.jobs import create_job

    status = create_job(jobs_dir)
    folder = jobs_dir / status.job_id
    artifacts.save(folder, Guide(title="G", device="P", mode="silent", steps=[_step(1, 0, 1)]))
    return status.job_id


def test_route_adds_and_removes(client, monkeypatch):
    http, jobs_dir = client
    job_id = _route_job(jobs_dir)
    done = Perception(steps=[perception.StepPerception(index=1, overlay="steps/01_overlay.jpg")])
    monkeypatch.setattr("app.routes.taps.add_fastener", lambda *args: done)
    monkeypatch.setattr("app.routes.taps.remove_fastener", lambda *args: done)
    response = http.post(f"/guides/{job_id}/steps/1/fasteners", json={"x": 0.5, "y": 0.5})
    assert response.status_code == 200
    assert response.json() == {"step": 1, "fasteners": 0, "overlay": "steps/01_overlay.jpg"}
    assert http.post(f"/guides/{job_id}/steps/1/fasteners/1/remove").status_code == 200


def test_route_errors(client, monkeypatch):
    http, jobs_dir = client
    assert http.post("/guides/nope/steps/1/fasteners", json={"x": 0, "y": 0}).status_code == 404
    job_id = _route_job(jobs_dir)

    def refuse(*args):
        raise tap.TapError("SAM found nothing to follow there")

    monkeypatch.setattr("app.routes.taps.add_fastener", refuse)
    response = http.post(f"/guides/{job_id}/steps/1/fasteners", json={"x": 0.5, "y": 0.5})
    assert response.status_code == 400 and "nothing" in response.json()["error"]
    monkeypatch.setattr("app.routes.taps.is_running", lambda *args: True)
    response = http.post(f"/guides/{job_id}/steps/1/fasteners", json={"x": 0.5, "y": 0.5})
    assert response.status_code == 409
