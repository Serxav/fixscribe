"""Strange but well-formed model answers, run through the whole pipeline.

Spark's answers depend on the repair, so each case here is an answer a real video could bring:
no steps, sixty steps, times past the end, a category with no profile, a professional-only job,
ten thousand screws. Whatever comes back, the job must end cleanly: "done" with a guide that
passes the schema, or "failed" with a sentence a person can read. Never a crash.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from app import artifacts, meta_client
from app.config import Settings
from app.meta_client import Detection
from app.pipeline.runner import default_stages, run_job
from app.schemas import Guide
from tests.test_pipeline_full import ANSWER, IDENTITY, REFINED, FakeMeta, new_job

LONG = "Remove the cover carefully. " * 400
STEP = ANSWER["steps"][0]


def steps(*items):
    return {**ANSWER, "steps": [{**STEP, **item} for item in items]}


ANALYSES = {
    "no steps": {**ANSWER, "steps": []},
    "sixty tiny steps": steps(*({"start_s": i * 0.1, "end_s": i * 0.1 + 0.1} for i in range(60))),
    "end before start": steps({"start_s": 6.0, "end_s": 1.0}),
    "all past the end": steps({"start_s": 50.0, "end_s": 90.0}, {"start_s": 95.0, "end_s": 99.0}),
    "negative times": steps({"start_s": -5.0, "end_s": -1.0}),
    "zero length": steps({"start_s": 3.0, "end_s": 3.0}),
    "same span twice": steps({}, {}),
    "huge numbers": steps({"start_s": 0.0, "end_s": 1e12, "screw_count": 10**6, "fastener_s": 1e9}),
    "empty texts": steps({"title": "", "instruction": "", "target_part": "", "removes": [""]}),
    "very long texts": {**steps({"title": LONG[:400], "instruction": LONG}), "summary": LONG},
    "unknown action": steps({"action": "explode", "removes": [f"part {i}" for i in range(50)]}),
    "no action": steps({"action": None, "target_part": None, "removes": []}),
    "emoji and accents": steps({"title": "Quita la tapa 🔧", "target_part": "tapa trasera ñ"}),
    "confidence as percent": steps({"confidence": 85}),
    "only the bare minimum": {"steps": [{"title": "Open it", "start_s": 0.0, "end_s": 4.0}]},
    "strange evidence": steps({"evidence": [{"t_s": -3, "source": "video", "text": ""}] * 30}),
}

IDENTITIES = {
    "category with no profile": {**IDENTITY, "category": "spaceship", "hazards": ["warp core"]},
    "professional only": {**IDENTITY, "category": "appliances", "hazards": ["gas"]},
    "an assembly video": {**IDENTITY, "category": "furniture", "task": "assemble", "hazards": []},
    "nothing known": {**IDENTITY, "object_name": "", "category": "", "task": "", "hazards": []},
    "odd confidence": {**IDENTITY, "confidence": 7, "language": "xx", "skill": "wizard"},
}

REFINES = {
    "refine moves the step out of the video": {**REFINED, "start_s": 80.0, "end_s": 70.0},
    "refine says nothing": {},
}


def fake_with(analysis=ANSWER, identity=IDENTITY, refined=REFINED):
    class Strange(FakeMeta):
        def respond(self, **kwargs):
            name = kwargs["text"]["format"]["name"]
            answer = {"refined_step": refined, "repair_identity": identity}.get(name, analysis)
            return SimpleNamespace(output_text=json.dumps(answer))

    return Strange


def ends_cleanly(tmp_path, monkeypatch, fake):
    monkeypatch.setattr(meta_client, "_factory", fake)
    FakeMeta.calls = []
    jobs, job_id = new_job(tmp_path)
    status = run_job(job_id, Settings(model_api_key="", data_dir=tmp_path), default_stages(), jobs)
    if status.state == "failed":
        assert status.error and "Traceback" not in status.error
        assert len(status.error) < 300
        return status, None
    assert status.state == "done", status.error
    guide = artifacts.load(jobs / job_id, Guide)  # passes the schema
    for step in guide.steps:
        assert 0 <= step.start_s <= step.end_s <= guide.duration_s + 0.01
    pages_open(tmp_path, job_id)
    return status, guide


def pages_open(tmp_path, job_id):
    """Every page and file a visitor opens for this guide answers, never a server error."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes.upload import settings_dep

    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=tmp_path)
    try:
        client = TestClient(app)
        pages = ("", "/film", "/live", "/tray", "/export.md")
        paths = [f"/guides/{job_id}{page}" for page in pages]
        paths += [f"/jobs/{job_id}", f"/api/jobs/{job_id}", f"/jobs/{job_id}/console"]
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
    finally:
        app.dependency_overrides.pop(settings_dep, None)


CANNOT_BE_SAVED = {"no steps", "all past the end"}  # nothing in the video to show


@pytest.mark.parametrize("case", list(ANALYSES))
def test_a_strange_analysis_never_crashes(tmp_path, monkeypatch, case):
    status, guide = ends_cleanly(tmp_path, monkeypatch, fake_with(analysis=ANALYSES[case]))
    if case in CANNOT_BE_SAVED:
        assert status.state == "failed" and status.error.startswith("plan failed: no repair step")
    else:
        assert guide is not None and guide.steps, status.error
        assert not status.warnings  # Spark's slip is mended quietly, never a stage lost


@pytest.mark.parametrize("case", list(IDENTITIES))
def test_a_strange_identity_never_crashes(tmp_path, monkeypatch, case):
    status, guide = ends_cleanly(tmp_path, monkeypatch, fake_with(identity=IDENTITIES[case]))
    assert guide is not None and not status.warnings, status.warnings
    if case == "professional only":
        assert guide.safety is not None and guide.safety.level == "professional_only"
        assert not guide.reassembly  # no instructions at all for a professional-only job
        assert all("qualified professional" in step.instruction for step in guide.steps)


@pytest.mark.parametrize("case", list(REFINES))
def test_a_strange_refine_never_crashes(tmp_path, monkeypatch, case):
    ends_cleanly(tmp_path, monkeypatch, fake_with(refined=REFINES[case]))


class SamEverywhere(FakeMeta):
    """SAM answers with a mask over the whole frame, and Spark points at the frame's edges."""

    def segment(self, image_path, concept, max_side=1280):
        found = [
            Detection(str(i), (0.0, 0.0, 100.0, 100.0), 1.0, None, None, None) for i in range(40)
        ]
        return found, (100, 100)

    def ground(self, image_path, query, *, context="", max_boxes=8, **kwargs):
        return [SimpleNamespace(label="screw", box=[0, 0, 1000, 1000])] * max_boxes


def test_sam_finding_everything_never_crashes(tmp_path, monkeypatch):
    ends_cleanly(tmp_path, monkeypatch, SamEverywhere)


def test_the_cases_do_not_share_state():
    assert copy.deepcopy(ANSWER) == ANSWER and ANSWER["steps"][0]["start_s"] == 0.5


def _job_from(tmp_path, *ffmpeg_args, cut_bytes=False):
    import subprocess

    from app.jobs import create_job

    jobs = tmp_path / "jobs"
    job_id = create_job(jobs).job_id
    original = jobs / job_id / "original.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *ffmpeg_args, str(original)], check=True)
    if cut_bytes:
        data = original.read_bytes()
        original.write_bytes(data[: len(data) // 2])
    return jobs, job_id


ODD_VIDEOS = {
    "half a second": ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-t", "0.5",
                      "-pix_fmt", "yuv420p"],
    "sound only": ["-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:a", "aac"],
    "tiny picture": ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=30", "-t", "3",
                     "-pix_fmt", "yuv420p"],
    "black and silent": ["-f", "lavfi", "-i", "color=c=black:size=640x360:rate=30", "-t", "4",
                         "-pix_fmt", "yuv420p"],
}  # fmt: skip


@pytest.mark.parametrize("case", [*ODD_VIDEOS, "cut off half way"])
def test_an_odd_video_ends_cleanly(tmp_path, monkeypatch, case):
    monkeypatch.setattr(meta_client, "_factory", fake_with())
    if case == "cut off half way":
        args = ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-t", "4", "-pix_fmt",
                "yuv420p"]  # fmt: skip
        jobs, job_id = _job_from(tmp_path, *args, cut_bytes=True)
    else:
        jobs, job_id = _job_from(tmp_path, *ODD_VIDEOS[case])
    status = run_job(job_id, Settings(model_api_key="", data_dir=tmp_path), default_stages(), jobs)
    assert status.state in ("done", "failed")
    if status.state == "failed":
        assert status.error and len(status.error) < 300 and "Traceback" not in status.error
    else:
        artifacts.load(jobs / job_id, Guide)
