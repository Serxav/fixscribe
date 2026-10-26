import pytest

from app.jobs import create_job, read_status
from app.pipeline.runner import JobAlreadyRunning, Stage, is_running, job_lock, run_job

SETTINGS = object()  # stages in these tests do not read settings


def write_file(name):
    def run(folder, settings):
        (folder / name).write_text("ok")

    return run


def fail(message):
    def run(folder, settings):
        raise RuntimeError(message)

    return run


def test_runs_stages_in_order_and_finishes(tmp_path):
    job_id = create_job(tmp_path).job_id
    order = []
    stages = [
        Stage("one", lambda folder, s: order.append("one")),
        Stage("two", write_file("two.txt")),
    ]
    status = run_job(job_id, SETTINGS, stages, tmp_path)
    assert order == ["one"]
    assert (tmp_path / job_id / "two.txt").exists()
    assert status.state == "done"
    assert status.progress == 1.0
    assert status.stage is None


def test_progress_is_saved_before_each_stage(tmp_path):
    job_id = create_job(tmp_path).job_id
    seen = []

    def record(folder, settings):
        status = read_status(job_id, tmp_path)
        seen.append((status.stage, status.progress))

    stages = [Stage("ingest", record, weight=1), Stage("analyze", record, weight=3)]
    run_job(job_id, SETTINGS, stages, tmp_path)
    assert seen == [("ingest", 0.0), ("analyze", 0.25)]


def test_failing_stage_stops_job_with_message(tmp_path):
    job_id = create_job(tmp_path).job_id
    stages = [Stage("ingest", fail("video too long")), Stage("never", write_file("x"))]
    status = run_job(job_id, SETTINGS, stages, tmp_path)
    assert status.state == "failed"
    assert status.stage == "ingest"
    assert status.error == "ingest failed: video too long"
    assert not (tmp_path / job_id / "x").exists()
    assert read_status(job_id, tmp_path).state == "failed"


def test_optional_stage_failure_becomes_warning(tmp_path):
    job_id = create_job(tmp_path).job_id
    stages = [
        Stage("inspector", fail("tool limit"), optional=True),
        Stage("assembly", write_file("guide.json")),
    ]
    status = run_job(job_id, SETTINGS, stages, tmp_path)
    assert status.state == "done"
    assert status.warnings == ["inspector failed: tool limit"]
    assert (tmp_path / job_id / "guide.json").exists()


def test_long_error_is_cut(tmp_path):
    job_id = create_job(tmp_path).job_id
    status = run_job(job_id, SETTINGS, [Stage("analyze", fail("x" * 1000))], tmp_path)
    assert len(status.error) == 300


def test_rerun_clears_old_error(tmp_path):
    job_id = create_job(tmp_path).job_id
    run_job(job_id, SETTINGS, [Stage("ingest", fail("boom"))], tmp_path)
    status = run_job(job_id, SETTINGS, [Stage("ingest", write_file("ok"))], tmp_path)
    assert status.state == "done"
    assert status.error is None


def test_same_job_cannot_run_twice(tmp_path):
    job_id = create_job(tmp_path).job_id
    with job_lock(tmp_path / job_id):
        assert is_running(job_id, tmp_path)
        with pytest.raises(JobAlreadyRunning):
            run_job(job_id, SETTINGS, [], tmp_path)
    assert not is_running(job_id, tmp_path)


def test_bad_job_id_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_job("../etc", SETTINGS, [], tmp_path)
