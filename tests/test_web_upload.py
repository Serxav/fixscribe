"""Web upload and job progress pages (task 008). No real pipeline process starts here."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import create_job, read_status
from app.main import app
from app.routes.upload import settings_dep


@pytest.fixture()
def jobs_tmp(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    yield data_dir / "jobs"
    app.dependency_overrides.pop(settings_dep, None)


@pytest.fixture()
def no_start(monkeypatch):
    calls: list[tuple] = []

    def fake_start(job_id, jobs_dir=None):
        calls.append((job_id, jobs_dir))

    monkeypatch.setattr("app.routes.upload.start_job", fake_start)
    return calls


def test_index_has_camera_input(jobs_tmp, no_start):
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert 'capture="environment"' in response.text
    assert 'name="video"' in response.text


def test_upload_mov_starts_job(jobs_tmp, no_start):
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"video": ("repair.mov", b"0123456789", "video/quicktime")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/jobs/")
    job_id = location.rsplit("/", 1)[-1]
    assert (jobs_tmp / job_id / "original.mov").read_bytes() == b"0123456789"
    assert len(no_start) == 1
    assert no_start[0][0] == job_id


def test_upload_txt_is_rejected(jobs_tmp, no_start):
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"video": ("notes.txt", b"hello", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert not jobs_tmp.exists() or list(jobs_tmp.iterdir()) == []
    assert no_start == []


def test_upload_daily_limit(jobs_tmp, no_start, tmp_path):
    data_dir = tmp_path / "data"
    app.dependency_overrides[settings_dep] = lambda: Settings(
        model_api_key="", data_dir=data_dir, daily_job_limit=0
    )
    response = TestClient(app).post(
        "/upload",
        files={"video": ("repair.mp4", b"0123", "video/mp4")},
        follow_redirects=False,
    )
    assert response.status_code == 429
    assert "Daily limit reached, try tomorrow." in response.text
    assert no_start == []


def test_upload_too_big_marks_job_failed(jobs_tmp, no_start, monkeypatch):
    import app.routes.upload as upload_module

    monkeypatch.setattr(upload_module, "MAX_UPLOAD_BYTES", 10)
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"video": ("repair.mp4", b"0123456789A", "video/mp4")},
        follow_redirects=False,
    )
    assert response.status_code == 413
    folders = list(jobs_tmp.iterdir())
    assert len(folders) == 1
    status = read_status(folders[0].name, jobs_tmp)
    assert status.state == "failed"
    assert list(folders[0].glob("original.*")) == []
    assert no_start == []


def test_api_status_and_bad_ids(jobs_tmp, no_start):
    client = TestClient(app)
    status = create_job(jobs_tmp)
    response = client.get(f"/api/jobs/{status.job_id}")
    assert response.status_code == 200
    assert "state" in response.json()
    assert client.get("/api/jobs/nothere").status_code == 404
    assert client.get("/api/jobs/nothere").json() == {"detail": "job not found"}
    assert client.get("/jobs/../etc").status_code == 404
    assert client.get("/jobs/nothere").status_code == 404


def test_job_page_links_job_js(jobs_tmp, no_start):
    client = TestClient(app)
    status = create_job(jobs_tmp)
    response = client.get(f"/jobs/{status.job_id}")
    assert response.status_code == 200
    assert "/static/job.js" in response.text
    assert status.job_id in response.text


def test_health_still_ok(jobs_tmp, no_start):
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_job_js_has_stage_labels():
    text = Path("web/static/job.js").read_text()
    for label in (
        "Preparing the video",
        "Listening to the narration",
        "Finding the steps",
        "Watching the repair",
        "Writing the guide",
        "Picking the best photos",
    ):
        assert label in text
    assert "2000" in text
    assert "guide-link" in text
    assert "retry-link" in text
    page = Path("web/templates/job.html").read_text()
    assert "Open the guide" in page
    assert "Try another video" in page


def test_job_that_cannot_start_is_marked_failed(tmp_path, monkeypatch):
    from app.jobs import read_status
    from app.main import app
    from app.routes.upload import settings_dep

    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=tmp_path)

    def broken_start(job_id, jobs_dir):
        raise OSError("no python")

    monkeypatch.setattr("app.routes.upload.start_job", broken_start)
    try:
        response = TestClient(app).post(
            "/upload", files={"video": ("clip.mp4", b"0" * 10, "video/mp4")}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 500
    (job,) = (tmp_path / "jobs").iterdir()
    assert read_status(job.name, tmp_path / "jobs").state == "failed"
