"""Step check backend and route. SAM is faked, stills are synthetic, no network."""

import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import artifacts, meta_client
from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.meta_client import BudgetExceeded, Detection
from app.pipeline import stepcheck
from app.pipeline.perception import AFTER_S
from app.pipeline.stepcheck import (
    MAX_CHECKS_PER_JOB,
    MAX_PHOTO_BYTES,
    StepCheckError,
    check_step,
    load_photo,
    reference_still,
)
from app.routes.upload import settings_dep
from app.schemas import (
    Guide,
    IngestInfo,
    Perception,
    ScrewMap,
    SourceVideo,
    Step,
    StepPerception,
)

IDENTITY = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


def _det(box, confidence=0.9):
    return Detection(
        object_id="x",
        box=tuple(float(v) for v in box),
        confidence=confidence,
        mask=None,
        mask_size=None,
        mask_bounds=None,
    )


class FakeClient:
    """Fake SAM: sees a fixed number of fasteners on whatever crop it is sent."""

    def __init__(self, count=0, fail_budget=False):
        self.count = count
        self.fail_budget = fail_budget
        self.calls = []

    def segment(self, image_path, concept, **kwargs):
        image = cv2.imread(str(image_path))
        assert image is not None
        height, width = image.shape[:2]
        self.calls.append((image_path.name, concept))
        if self.fail_budget:
            raise BudgetExceeded("budget reached")
        boxes = [_det((10.0, 10.0 + 40.0 * i, 34.0, 34.0 + 40.0 * i)) for i in range(self.count)]
        return boxes, (width, height)


def _photo_bytes(width=200, height=200):
    rng = np.random.default_rng(3)
    image = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def _step(index=1, screws=True, kind="bolt", count=2):
    return Step(
        index=index,
        title=f"Step {index}",
        instruction=f"Do step {index}.",
        start_s=0.0,
        end_s=10.0,
        screws=ScrewMap(count=count, kind=kind) if screws else None,
    )


def _job(tmp_path, steps, perceived="default"):
    guide = Guide(
        title="Fix the brakes",
        device="Phone",
        mode="silent",
        duration_s=60.0,
        steps=steps,
    )
    artifacts.save(tmp_path, guide)
    if perceived == "default":
        perceived = [
            StepPerception(index=step.index, screws_before=2, screws_after=0)
            for step in steps
            if step.screws
        ]
    if perceived is not None:
        artifacts.save(tmp_path, Perception(steps=perceived, sam_calls=0))
    return Settings(model_api_key="", data_dir=tmp_path)


def _ref(job_dir, index=1):
    image = np.full((200, 200, 3), 120, dtype=np.uint8)
    path = job_dir / "checks" / f"ref_{index:02d}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)
    return path


def _patch(monkeypatch, ref_path, matrix=IDENTITY):
    monkeypatch.setattr(stepcheck, "reference_still", lambda *args: ref_path)
    monkeypatch.setattr(stepcheck, "align_after_to_before", lambda *args: matrix)


def test_done_when_nothing_left(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path))
    fake = FakeClient(count=0)

    result = check_step(tmp_path, settings, 1, _photo_bytes(), client=fake)

    assert result.verdict == "done"
    assert result.message == "No bolts left where the guide removes them."
    assert result.fastener_kind == "bolt"
    assert result.expected_left == 0
    assert result.found == 0
    assert result.boxes == []
    assert result.aligned is True
    assert result.sam_calls == 1
    assert (tmp_path / "checks" / "step_01_1.json").is_file()

    again = check_step(tmp_path, settings, 1, _photo_bytes(), client=fake)
    assert (tmp_path / "checks" / "step_01_2.json").is_file()
    assert again.step == 1


def test_not_yet_names_remaining_bolts(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path))
    fake = FakeClient(count=2)

    result = check_step(tmp_path, settings, 1, _photo_bytes(), client=fake)

    assert result.verdict == "not_yet"
    assert result.message == "2 bolts are still in place."
    assert result.found == 2
    assert len(result.boxes) == 2
    assert result.aligned is True


def test_unclear_when_photo_does_not_align(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path), matrix=None)
    fake = FakeClient(count=2)

    result = check_step(tmp_path, settings, 1, _photo_bytes(), client=fake)

    assert result.verdict == "unclear"
    assert result.message == ("SAM found 2 bolts; the photo could not be matched to the guide.")
    assert result.aligned is False
    assert result.found == 2
    assert (tmp_path / "checks" / "step_01_1.json").is_file()


def test_unclear_without_guide_measurement(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)], perceived=None)
    _patch(monkeypatch, _ref(tmp_path))
    fake = FakeClient(count=1)

    result = check_step(tmp_path, settings, 1, _photo_bytes(), client=fake)

    assert result.verdict == "unclear"
    assert result.expected_left is None
    assert "SAM found 1 bolts" in result.message


def test_no_fastener_step_needs_no_sam_call(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1), _step(2, screws=False)])
    _patch(monkeypatch, _ref(tmp_path))
    fake = FakeClient(count=2)

    result = check_step(tmp_path, settings, 2, _photo_bytes(), client=fake)

    assert result.verdict == "unclear"
    assert result.message == (
        "This step has no fasteners to check. Compare your photo with the guide image."
    )
    assert result.fastener_kind == "screw"
    assert result.found is None
    assert fake.calls == []
    assert (tmp_path / "checks" / "step_02_1.json").is_file()


def test_unknown_step(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path))

    with pytest.raises(StepCheckError, match="unknown step"):
        check_step(tmp_path, settings, 9, _photo_bytes(), client=FakeClient())


def test_too_large_photo(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path))

    with pytest.raises(StepCheckError, match="too big"):
        check_step(tmp_path, settings, 1, b"x" * (MAX_PHOTO_BYTES + 1), client=FakeClient())


def test_unreadable_photo(tmp_path):
    with pytest.raises(StepCheckError, match="could not read"):
        load_photo(b"not a photo")
    with pytest.raises(StepCheckError, match="empty"):
        load_photo(b"")


def test_limit_reached(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path))
    checks = tmp_path / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    for number in range(1, MAX_CHECKS_PER_JOB + 1):
        (checks / f"step_01_{number}.json").write_text("{}")

    with pytest.raises(StepCheckError, match="check limit"):
        check_step(tmp_path, settings, 1, _photo_bytes(), client=FakeClient())


def test_budget_exceeded(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    _patch(monkeypatch, _ref(tmp_path))

    with pytest.raises(StepCheckError, match="budget reached"):
        check_step(tmp_path, settings, 1, _photo_bytes(), client=FakeClient(fail_budget=True))


def test_exif_rotated_jpeg_is_turned_upright():
    rgb = np.zeros((20, 40, 3), dtype=np.uint8)
    rgb[:, :20] = (255, 0, 0)
    stored = Image.fromarray(rgb, mode="RGB").transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6  # phones store portrait photos rotated, with this tag to fix them
    buf = io.BytesIO()
    stored.save(buf, format="PNG", exif=exif)

    image = load_photo(buf.getvalue())

    assert image.shape == (20, 40, 3)
    assert (image[10, 5] == (0, 0, 255)).all()
    assert (image[10, 30] == (0, 0, 0)).all()


def test_reference_still_reuses_file_and_needs_source(tmp_path):
    settings = _job(tmp_path, [_step(1)])
    guide = artifacts.load(tmp_path, Guide)
    reused = _ref(tmp_path)

    assert reference_still(tmp_path, guide, guide.steps[0]) == reused

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _job(fresh, [_step(1)])
    other = artifacts.load(fresh, Guide)
    with pytest.raises(StepCheckError, match="video source"):
        reference_still(fresh, other, other.steps[0])
    _ = settings


def test_reference_still_extracts_after_the_step(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1)])
    guide = artifacts.load(tmp_path, Guide)
    source = SourceVideo(filename="original.mp4", width=640, height=480, duration_s=60.0)
    artifacts.save(
        tmp_path,
        IngestInfo(duration_s=60.0, width=640, height=480, has_audio=False, source=source),
    )
    (tmp_path / "original.mp4").write_bytes(b"fake-video")
    seen = {}

    def fake_extract(original, src, t, dst, max_side=None):
        seen["t"] = t
        seen["dst"] = dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(dst), np.full((8, 8, 3), 7, dtype=np.uint8))

    monkeypatch.setattr(stepcheck, "extract_still", fake_extract)

    first = reference_still(tmp_path, guide, guide.steps[0])

    assert first == tmp_path / "checks" / "ref_01.png"
    assert seen["t"] == pytest.approx(10.0 + AFTER_S)
    second = reference_still(tmp_path, guide, guide.steps[0])
    assert second == first
    _ = settings


@pytest.fixture()
def jobs_tmp(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fake = FakeClient(count=0)
    monkeypatch.setattr(meta_client, "_factory", lambda *args, **kwargs: fake)
    monkeypatch.setattr(stepcheck, "align_after_to_before", lambda *args: IDENTITY)
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield (data_dir / "jobs", fake)
    app.dependency_overrides.pop(settings_dep, None)


def _route_job(jobs_dir, monkeypatch, fake):
    status = create_job(jobs_dir)
    folder = jobs_dir / status.job_id
    artifacts.save(folder, Guide(title="G", device="P", mode="silent", steps=[_step(1)]))
    artifacts.save(
        folder,
        Perception(
            steps=[StepPerception(index=1, screws_before=2, screws_after=0)],
            sam_calls=0,
        ),
    )
    ref = _ref(folder)
    monkeypatch.setattr(stepcheck, "reference_still", lambda *args: ref)
    return status.job_id


def test_route_returns_verdict_as_json(jobs_tmp, monkeypatch):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir, monkeypatch, fake)

    response = TestClient(app).post(
        f"/guides/{job_id}/steps/1/check",
        files={"photo": ("photo.png", _photo_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "done"
    assert body["step"] == 1
    assert body["message"] == "No bolts left where the guide removes them."
    assert fake.calls, "the route must really count fasteners through SAM"


def test_route_unknown_step_is_400(jobs_tmp, monkeypatch):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir, monkeypatch, fake)

    response = TestClient(app).post(
        f"/guides/{job_id}/steps/9/check",
        files={"photo": ("photo.png", _photo_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert "unknown step" in response.json()["error"]


def test_route_limit_is_429(jobs_tmp, monkeypatch):
    jobs_dir, fake = jobs_tmp
    job_id = _route_job(jobs_dir, monkeypatch, fake)
    checks = jobs_dir / job_id / "checks"
    for number in range(1, MAX_CHECKS_PER_JOB + 1):
        (checks / f"step_01_{number}.json").write_text("{}")

    response = TestClient(app).post(
        f"/guides/{job_id}/steps/1/check",
        files={"photo": ("photo.png", _photo_bytes(), "image/png")},
    )

    assert response.status_code == 429
    assert "check limit" in response.json()["error"]


def test_route_bad_job_and_missing_guide_are_404(jobs_tmp, monkeypatch):
    jobs_dir, fake = jobs_tmp
    client = TestClient(app)

    response = client.post(
        "/guides/nothere/steps/1/check",
        files={"photo": ("photo.png", _photo_bytes(), "image/png")},
    )
    assert response.status_code == 404

    job_id = _route_job(jobs_dir, monkeypatch, fake)
    (jobs_dir / job_id / "guide.json").unlink()
    response = client.post(
        f"/guides/{job_id}/steps/1/check",
        files={"photo": ("photo.png", _photo_bytes(), "image/png")},
    )
    assert response.status_code == 404
