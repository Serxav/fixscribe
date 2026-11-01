"""Limits that protect the budget and the files of whoever uploads a video."""

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.agent import tools
from app.config import Settings
from app.demo import is_write_to_sample
from app.jobs import claim_daily_slot, create_job
from app.main import app
from app.pipeline import ingest
from app.routes.upload import settings_dep
from scripts import pack_demo
from tests.video_factory import make_video

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_deleting_a_job_does_not_give_its_slot_back(tmp_path):
    jobs = tmp_path / "jobs"
    assert claim_daily_slot(jobs, 2)
    folder = jobs / create_job(jobs).job_id
    assert claim_daily_slot(jobs, 2)
    shutil.rmtree(folder)
    assert not claim_daily_slot(jobs, 2)


def test_jobs_already_there_count_towards_the_limit(tmp_path):
    jobs = tmp_path / "jobs"
    create_job(jobs)
    assert not claim_daily_slot(jobs, 1)


@pytest.mark.parametrize("action", ["start", "resume", "answer", "signoff"])
def test_the_agent_stays_off_when_the_server_says_so(tmp_path, action):
    settings = Settings(model_api_key="", data_dir=tmp_path, enable_inspector=False)
    job_id = create_job(settings.jobs_dir).job_id
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        response = TestClient(app).post(f"/api/jobs/{job_id}/agent/{action}", json={})
    finally:
        app.dependency_overrides.pop(settings_dep, None)
    assert response.status_code == 403


def test_sample_guide_rejects_writes_only():
    assert is_write_to_sample("POST", "/api/jobs/abc/delete", "abc")
    assert not is_write_to_sample("GET", "/api/jobs/abc", "abc")


@needs_ffmpeg
def test_a_playlist_named_mp4_is_refused(tmp_path):
    (tmp_path / "secret.txt").write_text("key")
    fake = tmp_path / "original.mp4"
    fake.write_text(f"#EXTM3U\n#EXTINF:1,\nfile://{tmp_path}/secret.txt\n#EXT-X-ENDLIST\n")
    with pytest.raises(ingest.IngestError):
        ingest.probe_source(fake)


@needs_ffmpeg
@pytest.mark.parametrize("name", ["phone.mp4", "phone.mov", "phone.m4v"])
def test_real_phone_formats_still_open(tmp_path, name):
    video = tmp_path / "base.mp4"
    make_video(video, seconds=1)
    target = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-c", "copy", str(target)], check=True
    )
    assert ingest.probe_source(target).width > 0


def test_a_pack_leaves_out_every_original(tmp_path, monkeypatch):
    job = tmp_path / "abc"
    job.mkdir()
    for name in ("guide.json", "original.mov", "video.mp4", "state.json", "spend.json"):
        (job / name).write_text("{}")
    monkeypatch.chdir(tmp_path)
    assert pack_demo.main([str(job)]) == 0
    assert sorted(p.name for p in (tmp_path / "demo" / "abc").iterdir()) == [
        "guide.json",
        "video.mp4",
    ]


def test_the_agent_can_only_ask_about_a_frame(tmp_path):
    assert tools.frame_time("frames/t1.5.jpg") == 1.5
    assert tools.frame_time("../../.env") is None
