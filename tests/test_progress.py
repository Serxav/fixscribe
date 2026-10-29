"""Progress story: the progress page shows each stage's real findings as soon as they exist."""

from fastapi.testclient import TestClient

from app import artifacts, progress
from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.routes.upload import settings_dep
from app.schemas import Analysis, DraftStep, Identity, IngestInfo, Safety, Transcript, Turn


def test_a_new_job_has_nothing_to_show(tmp_path):
    assert progress.story(tmp_path, "abc") == {}


def test_findings_appear_stage_by_stage(tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"x")
    artifacts.save(tmp_path, IngestInfo(duration_s=60, width=1920, height=1080, has_audio=True))
    artifacts.save(
        tmp_path,
        Identity(
            object_name="TV remote", category="electronics", task="repair", hazards=["sharp_edges"]
        ),
    )
    long_turn = "paso uno quitamos la tapa " * 20
    artifacts.save(
        tmp_path,
        Transcript(mode="narrated", turns=[Turn(start_s=1.24, end_s=9, text=long_turn)]),
    )
    artifacts.save(
        tmp_path, Analysis(steps=[DraftStep(title="Open the cover", start_s=2, end_s=10)])
    )
    artifacts.save(tmp_path, Safety(level="caution", reasons=["Small parts."]))
    story = progress.story(tmp_path, "abc")
    assert story["video"] == {
        "url": "/media/abc/video.mp4",
        "duration_s": 60,
        "width": 1920,
        "height": 1080,
    }
    assert story["identity"]["object"] == "TV remote"
    assert story["identity"]["hazards"] == ["sharp edges"]
    turn = story["heard"]["turns"][0]
    assert turn["t"] == 1.2 and turn["text"].endswith("…") and len(turn["text"]) <= 221
    assert story["draft"] is True
    assert story["steps"][0]["title"] == "Open the cover" and story["steps"][0]["image"] is None
    assert story["safety"] == {"level": "caution", "reasons": ["Small parts."]}
    assert "fasteners" not in story


def test_a_half_written_file_is_left_out(tmp_path):
    (tmp_path / Identity.FILENAME).write_text("{not json", encoding="utf-8")
    assert progress.story(tmp_path, "abc") == {}


def test_the_status_api_carries_the_story(tmp_path):
    app.dependency_overrides[settings_dep] = lambda: Settings(data_dir=tmp_path)
    try:
        jobs = tmp_path / "jobs"
        job_id = create_job(jobs).job_id
        artifacts.save(jobs / job_id, Safety(level="normal"))
        data = TestClient(app).get(f"/api/jobs/{job_id}").json()
        assert data["story"]["safety"]["level"] == "normal"
    finally:
        app.dependency_overrides.pop(settings_dep, None)
