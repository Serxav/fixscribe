"""Chaos test: break each stage on purpose and check what the user gets.

Optional stage broken -> the job still finishes, guide.json is valid and the warning names the
stage. Required stage broken -> the job fails, says which stage, and `resume` finishes it once
the stage works again, without running the stages before it a second time.
"""

import dataclasses

import pytest

from app import artifacts, meta_client
from app.config import Settings
from app.pipeline.runner import default_stages, run_job
from app.schemas import Guide, Manifest
from tests.test_pipeline_full import FakeMeta, new_job

OPTIONAL = [stage.name for stage in default_stages() if stage.optional]
REQUIRED = [stage.name for stage in default_stages() if not stage.optional]


def _broken(name):
    def run(folder, settings):
        raise RuntimeError(f"{name} exploded")

    return run


def _stages_with(broken: str | None):
    return [
        dataclasses.replace(stage, run=_broken(stage.name)) if stage.name == broken else stage
        for stage in default_stages()
    ]


@pytest.fixture
def fake(monkeypatch):
    FakeMeta.calls = []
    monkeypatch.setattr(meta_client, "_factory", FakeMeta)


def test_every_stage_is_classified():
    assert set(OPTIONAL) == {
        "transcribe", "identify", "signals", "fusion", "refine", "frames", "perception",
        "motion", "proof", "learn",
    }  # fmt: skip
    assert REQUIRED == ["ingest", "scenes", "analyze", "plan", "safety", "publish"]


@pytest.mark.parametrize("broken", OPTIONAL)
def test_a_broken_optional_stage_still_gives_a_valid_guide(tmp_path, fake, broken):
    jobs, job_id = new_job(tmp_path)
    status = run_job(job_id, Settings(data_dir=tmp_path), _stages_with(broken), jobs)
    assert status.state == "done", status.error
    assert status.warnings == [f"{broken} failed: {broken} exploded"]
    folder = jobs / job_id
    guide = artifacts.load(folder, Guide)  # valid against the schema
    assert guide.steps
    assert artifacts.load(folder, Manifest).stages[broken].status == "failed"


@pytest.mark.parametrize("broken", REQUIRED)
def test_a_broken_required_stage_fails_clearly_and_resume_recovers(tmp_path, fake, broken):
    jobs, job_id = new_job(tmp_path)
    settings = Settings(data_dir=tmp_path)
    status = run_job(job_id, settings, _stages_with(broken), jobs)
    assert status.state == "failed"
    assert status.stage == broken
    assert status.error == f"{broken} failed: {broken} exploded"
    assert not (jobs / job_id / "guide.json").exists() or broken != "publish"

    status = run_job(job_id, settings, default_stages(), jobs, resume=True)
    assert status.state == "done", status.error
    manifest = artifacts.load(jobs / job_id, Manifest)
    order = [stage.name for stage in default_stages()]
    before = order[: order.index(broken)]
    assert all(manifest.stages[name].status == "skipped" for name in before)  # not paid twice
    assert manifest.stages[broken].status == "done"
    assert artifacts.load(jobs / job_id, Guide).steps
