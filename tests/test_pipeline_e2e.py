"""Whole-pipeline tests with real ffmpeg and no Meta calls."""

import json
import shutil
import subprocess
import sys

import pytest

from app.config import Settings
from app.jobs import create_job, read_status
from app.pipeline.runner import default_stages, run_job

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def make_upload(folder, seconds=2, size="1080x1920"):
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(folder / "original.mov"),
        ],
        check=True,
    )  # fmt: skip


def settings(tmp_path, **extra):
    return Settings(model_api_key="", data_dir=tmp_path, **extra)


def test_phone_video_goes_through_ingest(tmp_path):
    jobs = tmp_path / "jobs"
    job_id = create_job(jobs).job_id
    make_upload(jobs / job_id)
    status = run_job(job_id, settings(tmp_path), default_stages(), jobs)
    assert status.state == "done", status.error
    folder = jobs / job_id
    info = json.loads((folder / "ingest.json").read_text())
    assert (info["width"], info["height"]) == (720, 1280)
    assert (folder / "audio.wav").exists()


def test_too_long_video_fails_with_clear_message(tmp_path):
    jobs = tmp_path / "jobs"
    job_id = create_job(jobs).job_id
    make_upload(jobs / job_id, seconds=3)
    status = run_job(job_id, settings(tmp_path, max_video_seconds=1), default_stages(), jobs)
    assert status.state == "failed"
    assert status.error.startswith("ingest failed: video too long")


def test_runner_command_line(tmp_path):
    jobs = tmp_path / "jobs"
    job_id = create_job(jobs).job_id
    make_upload(jobs / job_id)
    result = subprocess.run(
        [sys.executable, "-m", "app.pipeline.runner", job_id, str(jobs)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,  # no .env is loaded from here
        env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "DATA_DIR": str(tmp_path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert read_status(job_id, jobs).state == "done"
