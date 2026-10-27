from app.config import Settings
from app.jobs import create_job
from app.routes.common import job_folder, load_guide


def test_one_jobs_folder_from_settings(tmp_path):
    assert Settings(data_dir=tmp_path).jobs_dir == tmp_path / "jobs"


def test_job_folder_rejects_bad_ids(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert job_folder("../../etc", settings) is None
    assert job_folder("a" * 12, settings) == tmp_path / "jobs" / ("a" * 12)


def test_load_guide_states(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert load_guide("nope", settings) == (None, None)  # bad id
    job_id = create_job(settings.jobs_dir).job_id
    folder, guide = load_guide(job_id, settings)
    assert folder == settings.jobs_dir / job_id and guide is None  # not ready
    (folder / "guide.json").write_text("{broken")
    assert load_guide(job_id, settings) == (folder, None)  # unreadable, never a crash
    (folder / "guide.json").write_text('{"title": "t", "device": "d", "mode": "silent"}')
    assert load_guide(job_id, settings)[1].title == "t"
