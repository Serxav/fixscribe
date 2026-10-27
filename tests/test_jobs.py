import json

import pytest
from pydantic import ValidationError

from app.jobs import (
    create_job,
    job_dir,
    jobs_created_today,
    read_status,
    update_status,
    write_json_atomic,
)


def test_create_job_makes_folder_and_status(tmp_path):
    status = create_job(tmp_path)
    folder = tmp_path / status.job_id
    assert folder.is_dir()
    saved = json.loads((folder / "status.json").read_text())
    assert saved["state"] == "queued"
    assert saved["progress"] == 0.0


def test_two_jobs_get_different_ids(tmp_path):
    assert create_job(tmp_path).job_id != create_job(tmp_path).job_id


def test_update_status_keeps_other_fields(tmp_path):
    job_id = create_job(tmp_path).job_id
    update_status(job_id, tmp_path, state="running", stage="ingest", progress=0.1)
    status = update_status(job_id, tmp_path, progress=0.5)
    assert status.state == "running"
    assert status.stage == "ingest"
    assert read_status(job_id, tmp_path).progress == 0.5


def test_failed_job_keeps_error(tmp_path):
    job_id = create_job(tmp_path).job_id
    update_status(job_id, tmp_path, state="failed", error="video too long")
    assert read_status(job_id, tmp_path).error == "video too long"


def test_bad_update_does_not_touch_file(tmp_path):
    job_id = create_job(tmp_path).job_id
    with pytest.raises(ValidationError):
        update_status(job_id, tmp_path, progress=2.0)
    assert read_status(job_id, tmp_path).progress == 0.0


def test_atomic_write_leaves_no_temp_files(tmp_path):
    path = tmp_path / "status.json"
    write_json_atomic(path, {"a": 1})
    write_json_atomic(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["status.json"]


@pytest.mark.parametrize(
    "bad_id", ["../etc", "ABC", "", "123", "0123456789ab/..", "0123456789ab\n"]
)
def test_bad_job_id_is_rejected(tmp_path, bad_id):
    with pytest.raises(ValueError):
        job_dir(bad_id, tmp_path)


def test_missing_job_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_status("0123456789ab", tmp_path)


def test_jobs_created_today(tmp_path):
    assert jobs_created_today(tmp_path / "missing") == 0
    create_job(tmp_path)
    old = create_job(tmp_path).job_id
    update_status(old, tmp_path, created_at="2026-01-01T00:00:00+00:00")
    assert jobs_created_today(tmp_path) == 1


def test_broken_status_does_not_block_daily_count(tmp_path):
    create_job(tmp_path)
    broken = create_job(tmp_path).job_id
    (tmp_path / broken / "status.json").write_text("{")
    assert jobs_created_today(tmp_path) == 1


def test_attempt_job_needs_a_reference_guide(tmp_path):
    import pytest

    from app.jobs import create_job

    guide_job = create_job(tmp_path).job_id
    with pytest.raises(FileNotFoundError):
        create_job(tmp_path, reference_job=guide_job)  # no guide.json yet
    with pytest.raises(ValueError):
        create_job(tmp_path, reference_job="../etc")
    (tmp_path / guide_job / "guide.json").write_text("{}")
    attempt = create_job(tmp_path, reference_job=guide_job)
    assert attempt.kind == "attempt" and attempt.reference_job == guide_job
    assert create_job(tmp_path).kind == "guide"
