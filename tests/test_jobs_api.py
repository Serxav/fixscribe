"""Progress API: every stage with its state, and "try again" from the failed stage."""

import pytest
from fastapi.testclient import TestClient

from app import artifacts
from app.config import Settings
from app.jobs import create_job, read_status, update_status
from app.main import app
from app.routes.upload import settings_dep
from app.schemas import Manifest, StageRecord


@pytest.fixture()
def jobs_dir(tmp_path, monkeypatch):
    app.dependency_overrides[settings_dep] = lambda: Settings(data_dir=tmp_path)
    started = []
    monkeypatch.setattr(
        "app.routes.jobs.start_job", lambda job_id, jobs, resume=False: started.append(resume)
    )
    yield tmp_path / "jobs", started
    app.dependency_overrides.pop(settings_dep, None)


def _record(status, error=None):
    return StageRecord(status=status, version="1", started_at="t", seconds=1.5, error=error)


def test_status_lists_every_stage_with_its_state(jobs_dir):
    jobs, _ = jobs_dir
    job_id = create_job(jobs).job_id
    folder = jobs / job_id
    manifest = Manifest(stages={"ingest": _record("done"), "transcribe": _record("skipped")})
    artifacts.save(folder, manifest)
    update_status(job_id, jobs, state="failed", stage="identify", error="identify failed: x")
    data = TestClient(app).get(f"/api/jobs/{job_id}").json()
    by_name = {stage["name"]: stage for stage in data["stages"]}
    assert data["stages"][0]["name"] == "ingest" and len(data["stages"]) == 16
    assert by_name["ingest"]["status"] == "done" and by_name["ingest"]["seconds"] == 1.5
    assert by_name["transcribe"]["status"] == "skipped"
    assert by_name["publish"]["status"] == "waiting"
    assert by_name["identify"]["label"] == "Identifying the object"


def test_running_stage_is_marked_running(jobs_dir):
    jobs, _ = jobs_dir
    job_id = create_job(jobs).job_id
    update_status(job_id, jobs, state="running", stage="analyze")
    from app.pipeline import runner

    # No runner holds the lock in a test: pretend one does, so the job is not marked stale.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "is_running", lambda *a: True)
        data = TestClient(app).get(f"/api/jobs/{job_id}").json()
    assert {s["name"]: s["status"] for s in data["stages"]}["analyze"] == "running"


def test_broken_manifest_never_breaks_the_api(jobs_dir):
    jobs, _ = jobs_dir
    job_id = create_job(jobs).job_id
    (jobs / job_id / "manifest.json").write_text("{not json")
    assert TestClient(app).get(f"/api/jobs/{job_id}").status_code == 200


def test_resume_restarts_a_failed_job(jobs_dir):
    jobs, started = jobs_dir
    job_id = create_job(jobs).job_id
    update_status(job_id, jobs, state="failed", stage="analyze", error="analyze failed")
    response = TestClient(app).post(f"/api/jobs/{job_id}/resume")
    assert response.status_code == 202
    assert started == [True]
    assert read_status(job_id, jobs).state == "queued"


def test_resume_refuses_jobs_that_did_not_fail(jobs_dir):
    jobs, started = jobs_dir
    job_id = create_job(jobs).job_id
    update_status(job_id, jobs, state="done")
    client = TestClient(app)
    assert client.post(f"/api/jobs/{job_id}/resume").status_code == 409
    assert client.post("/api/jobs/nothere/resume").status_code == 404
    assert started == []
