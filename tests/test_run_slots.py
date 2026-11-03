"""Only a few videos are processed at once; the others wait in line, not out of memory."""

import threading

from app.config import Settings
from app.jobs import create_job, read_status
from app.pipeline.runner import IN_LINE, Stage, run_job, run_slot


def test_a_third_runner_waits_until_a_place_frees(tmp_path):
    first, second = threading.Event(), threading.Event()
    waits = []
    with run_slot(tmp_path, 2, lambda: waits.append(1)):
        with run_slot(tmp_path, 2, lambda: waits.append(2)):
            assert waits == []  # two places, nobody waits

            def third():
                with run_slot(tmp_path, 2, lambda: first.set(), poll_s=0.01):
                    second.set()

            worker = threading.Thread(target=third)
            worker.start()
            assert first.wait(2)  # it found every place taken
            assert not second.wait(0.1)  # and does not run yet
        assert second.wait(2)  # one place was given back: it runs
        worker.join(2)


def test_zero_places_means_no_line(tmp_path):
    with run_slot(tmp_path, 0, lambda: None):
        with run_slot(tmp_path, 0, lambda: None):
            pass
    assert not list(tmp_path.iterdir())


def test_a_job_in_line_says_so_then_runs(tmp_path):
    settings = Settings(data_dir=tmp_path, max_running_jobs=1)
    jobs_dir = settings.jobs_dir
    job_id = create_job(jobs_dir).job_id
    seen = []
    stage = Stage("ingest", lambda folder, s: seen.append(read_status(job_id, jobs_dir).state))
    result = {}
    with run_slot(tmp_path, 1, lambda: None):  # another video holds the only place
        worker = threading.Thread(
            target=lambda: result.update(status=run_job(job_id, settings, [stage]))
        )
        worker.start()
        for _ in range(200):
            status = read_status(job_id, jobs_dir)
            if status.stage == IN_LINE:
                break
            threading.Event().wait(0.01)
        assert status.state == "queued" and status.stage == IN_LINE
    worker.join(10)
    assert result["status"].state == "done"
    assert seen == ["running"]
