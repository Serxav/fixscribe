"""The whole pipeline on a real (generated) video, with Meta replaced by a fake client."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app import artifacts
from app.config import Settings
from app.jobs import create_job
from app.pipeline import analyze, perception, refine, transcribe
from app.pipeline.publish import UNVERIFIED_SCREWS
from app.pipeline.runner import default_stages, run_job
from app.schemas import Guide, Manifest

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

TURNS = [
    {"turnId": 1, "startMs": 500, "endMs": 2500, "transcript": "Step one, remove the four screws"},
    {"turnId": 2, "startMs": 5000, "endMs": 6500, "transcript": "Paso dos, desconecta la batería"},
]

ANSWER = {
    "title": "Replace the battery",
    "device": "Test phone",
    "summary": "Open the phone and take out the battery.",
    "difficulty": "easy",
    "estimated_minutes": 10,
    "tools": ["Phillips #000"],
    "parts": ["back cover", "battery connector"],
    "warnings": [],
    "steps": [
        {
            "title": "Remove back cover",
            "instruction": "Remove the four screws and lift the back cover.",
            "start_s": 0.5,
            "end_s": 5.0,
            "target_part": "back cover",
            "action": "unscrew",
            "removes": ["back cover"],
            "screw_count": 4,
            "warnings": [],
            "evidence": [{"t_s": 2.0, "source": "video", "text": "screws out"}],
            "confidence": 0.9,
        },
        {
            "title": "Disconnect battery",
            "instruction": "Disconnect the battery connector.",
            "start_s": 5.0,
            "end_s": 99.0,  # past the end of the video: the guide builder must clamp it
            "target_part": "battery connector",
            "action": "disconnect",
            "removes": ["battery connector"],
            "screw_count": 0,
            "warnings": ["Disconnect the battery before anything else."],
            "evidence": [],
            "confidence": 0.4,
        },
    ],
}


REFINED = {
    "start_s": 0.6,
    "end_s": 4.8,
    "instruction": "Remove the four screws on the back cover.",
    "action": "unscrew",
    "removes": ["back cover"],
    "screw_count": 4,
    "warnings": [],
    "confidence": 0.95,
}


class FakeMeta:
    """Stands in for MetaClient in every stage that talks to Meta."""

    calls: list = []

    def __init__(self, settings, **kwargs):
        pass

    def transcribe(self, wav, **kwargs):
        FakeMeta.calls.append(("transcribe", kwargs))
        return {"sessionId": "s", "transcript": "", "audioDurationMs": 8000, "turns": TURNS}

    def upload_file(self, path):
        FakeMeta.calls.append(("upload", path.name))
        return "file-test"

    def respond(self, **kwargs):
        FakeMeta.calls.append(("respond", kwargs["input"][0]["content"][0]["text"]))
        if kwargs["text"]["format"]["name"] == "refined_step":  # Spark pass 2 on one step
            return SimpleNamespace(output_text=json.dumps(REFINED))
        return SimpleNamespace(output_text=json.dumps(ANSWER))

    def segment(self, image_path, concept, max_side=1280):
        FakeMeta.calls.append(("segment", concept))
        return [], (100, 100)  # SAM finds nothing: the guide must say screws are unverified

    def delete_file(self, file_id):
        FakeMeta.calls.append(("delete", file_id))


@pytest.fixture
def fake_meta(monkeypatch):
    FakeMeta.calls = []
    monkeypatch.setattr(transcribe, "MetaClient", FakeMeta)
    monkeypatch.setattr(analyze, "MetaClient", FakeMeta)
    monkeypatch.setattr(refine, "MetaClient", FakeMeta)
    monkeypatch.setattr(perception, "MetaClient", FakeMeta)
    return FakeMeta


def new_job(tmp_path, seconds=8):
    jobs = tmp_path / "jobs"
    job_id = create_job(jobs).job_id
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(jobs / job_id / "original.mp4"),
        ],
        check=True,
    )  # fmt: skip
    return jobs, job_id


def test_full_pipeline_builds_a_guide(tmp_path, fake_meta):
    jobs, job_id = new_job(tmp_path)
    status = run_job(job_id, Settings(model_api_key="", data_dir=tmp_path), default_stages(), jobs)
    assert status.state == "done", status.error

    folder = jobs / job_id
    scenes = json.loads((folder / "scenes.json").read_text())
    assert scenes["source"] == "voice"
    prompt = next(text for kind, text in fake_meta.calls if kind == "respond")
    assert "Step one, remove the four screws" in prompt
    assert "- step 1: 0.5–5.0 s" in prompt
    assert ("delete", "file-test") in fake_meta.calls

    guide = Guide.model_validate_json((folder / "guide.json").read_text())
    assert guide.mode == "narrated"
    assert [s.title for s in guide.steps] == ["Remove back cover", "Disconnect battery"]
    assert guide.steps[1].end_s <= guide.duration_s  # clamped to the real video length
    assert guide.steps[1].review == "needs_review"
    assert [r.action for r in guide.reassembly] == ["reconnect", "screw in"]
    assert (folder / "analysis_raw.txt").exists()
    # Honest output: Spark counted 4 screws but nothing verified them on the images yet.
    assert UNVERIFIED_SCREWS in guide.checks
    # Every stage left a record: version, time and cost.
    manifest = artifacts.load(folder, Manifest)
    assert list(manifest.stages) == [
        "ingest", "transcribe", "signals", "scenes", "analyze", "fusion", "refine", "plan",
        "frames", "perception", "publish",
    ]  # fmt: skip
    assert all(record.status == "done" for record in manifest.stages.values())
    # Pass 2 looked again at the screw step and its answer reached the guide.
    assert guide.steps[0].instruction == "Remove the four screws on the back cover."
    assert any(kind == "segment" and concept == "screw" for kind, concept in fake_meta.calls)
    assert guide.steps[0].image == "steps/01.jpg"
    assert (folder / guide.steps[0].clip).exists()


def test_bad_spark_answer_fails_the_job_cleanly(tmp_path, fake_meta, monkeypatch):
    monkeypatch.setattr(FakeMeta, "respond", lambda self, **kw: SimpleNamespace(output_text="{"))
    jobs, job_id = new_job(tmp_path)
    status = run_job(job_id, Settings(model_api_key="", data_dir=tmp_path), default_stages(), jobs)
    assert status.state == "failed"
    assert status.error == "analyze failed: Spark returned an invalid analysis"
    assert (jobs / job_id / "analysis_raw.txt").read_text() == "{"


def test_failed_transcription_still_gives_a_silent_guide(tmp_path, fake_meta, monkeypatch):
    from app.meta_client import MetaError

    def broken(self, wav, **kwargs):
        raise MetaError("asr status 500", status_code=500)

    monkeypatch.setattr(FakeMeta, "transcribe", broken)
    jobs, job_id = new_job(tmp_path)
    status = run_job(job_id, Settings(model_api_key="", data_dir=tmp_path), default_stages(), jobs)
    assert status.state == "done", status.error
    assert status.warnings == ["transcribe failed: asr status 500"]
    guide = Guide.model_validate_json((jobs / job_id / "guide.json").read_text())
    assert guide.mode == "silent"
