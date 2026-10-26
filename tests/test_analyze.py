"""Analyze stage tests. Everything uses fakes, never the network."""

import json
import types
from pathlib import Path

import httpx
import openai
import pytest

from app.config import Settings
from app.meta_client import MetaClient, MetaError
from app.pipeline.analyze import (
    ANALYZE_TIMEOUT_S,
    MAX_OUTPUT_TOKENS,
    TEXT_FORMAT,
    AnalyzeError,
    build_input,
    build_prompt,
    parse_analysis,
    run,
)
from app.schemas import Analysis

REQ = httpx.Request("POST", "https://api.meta.ai/v1/responses")

ANSWER = {
    "title": "Replace the battery",
    "device": "Phone X",
    "summary": "s",
    "difficulty": "easy",
    "estimated_minutes": 15,
    "tools": ["Phillips #000"],
    "parts": ["battery"],
    "warnings": [],
    "steps": [
        {
            "title": "Remove back cover",
            "instruction": "Remove the four screws.",
            "start_s": 1.5,
            "end_s": 12.0,
            "target_part": "back cover",
            "action": "unscrew",
            "removes": ["back cover"],
            "screw_count": 4,
            "warnings": [],
            "evidence": [{"t_s": 3.0, "source": "video", "text": "screws out"}],
            "confidence": 0.8,
        }
    ],
}


def status_error(status: int):
    response = httpx.Response(status, json={}, request=REQ)
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls(f"status {status}", response=response, body=None)


def fake_usage():
    return types.SimpleNamespace(
        input_tokens=1000,
        input_tokens_details=types.SimpleNamespace(cached_tokens=0),
        output_tokens=500,
    )


def fake_answer():
    return types.SimpleNamespace(output_text=json.dumps(ANSWER), usage=fake_usage())


class FakeResponses:
    """Fake for `client.responses`, mirroring tests/test_meta_client.py."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.kwargs: list[dict] = []

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeFiles:
    """Fake for `client.files`, mirroring tests/test_meta_client.py."""

    def __init__(self):
        self.created = 0
        self.deleted: list[str] = []

    def create(self, **kwargs):
        del kwargs
        self.created += 1
        return types.SimpleNamespace(id="file-abc")

    def delete(self, file_id):
        self.deleted.append(file_id)
        return types.SimpleNamespace(id=file_id)


def make_client(tmp_path: Path, results):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    fake = types.SimpleNamespace(files=FakeFiles(), responses=FakeResponses(results))
    client = MetaClient(settings, client=fake, sleep=lambda _: None)
    return client, fake


def make_job(
    job_dir: Path,
    *,
    with_transcript: bool = True,
    scenes_source: str = "voice",
    with_scenes: bool = True,
) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "video.mp4").write_bytes(b"fake-video-bytes")
    (job_dir / "ingest.json").write_text(json.dumps({"duration_s": 42.0}), encoding="utf-8")
    if with_transcript:
        (job_dir / "transcript.json").write_text(
            json.dumps(
                {
                    "mode": "narrated",
                    "turns": [
                        {
                            "start_s": 1.2,
                            "end_s": 3.4,
                            "text": "Step one, remove the screws",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    if with_scenes:
        (job_dir / "scenes.json").write_text(
            json.dumps(
                {
                    "source": scenes_source,
                    "segments": [{"start_s": 1.2, "end_s": 15.0}],
                }
            ),
            encoding="utf-8",
        )


def prompt_text(fake) -> str:
    assert fake.responses.calls == 1
    return fake.responses.kwargs[0]["input"][0]["content"][0]["text"]


def test_narrated_job_sends_schema_and_turns(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir)
    client, fake = make_client(tmp_path, [fake_answer()])

    result = run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    kwargs = fake.responses.kwargs[0]
    assert kwargs["text"] == TEXT_FORMAT
    assert kwargs["max_output_tokens"] == 16000
    assert MAX_OUTPUT_TOKENS == 16000
    prompt = prompt_text(fake)
    assert "- [1.2–3.4 s] Step one, remove the screws" in prompt
    assert "- step 1:" in prompt
    assert isinstance(result, Analysis)
    assert result.steps[0].screw_count == 4
    saved = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
    assert Analysis.model_validate(saved).title == "Replace the battery"


def test_silent_job_without_transcript_or_scenes(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir, with_transcript=False, with_scenes=False)
    client, fake = make_client(tmp_path, [fake_answer()])

    run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    prompt = prompt_text(fake)
    assert "silent" in prompt
    assert prompt.count("- (none)") == 2


def test_scenes_source_none_ignores_segments(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir, scenes_source="none")
    client, fake = make_client(tmp_path, [fake_answer()])

    run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    prompt = prompt_text(fake)
    assert "- step 1:" not in prompt
    assert "- (none)" in prompt


def test_build_prompt_leaves_no_placeholders():
    prompt = build_prompt(
        42.0,
        "narrated",
        [{"start_s": 1.2, "end_s": 3.4, "text": "Step one"}],
        [{"start_s": 1.2, "end_s": 15.0}],
    )
    assert "<<" not in prompt


def test_build_input_shape():
    result = build_input("do the repair", "file-123")
    assert len(result) == 1
    assert result[0]["role"] == "user"
    text_block, file_block = result[0]["content"]
    assert text_block == {"type": "input_text", "text": "do the repair"}
    assert file_block == {"type": "input_file", "file_id": "file-123"}


def test_broken_json_raises_but_deletes_file(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir)
    bad = types.SimpleNamespace(output_text="not json {{{", usage=fake_usage())
    client, fake = make_client(tmp_path, [bad])

    with pytest.raises(AnalyzeError):
        run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    assert fake.files.deleted == ["file-abc"]


def test_parse_analysis_rejects_empty_and_invalid():
    with pytest.raises(AnalyzeError, match="Spark returned an invalid analysis"):
        parse_analysis("")
    with pytest.raises(AnalyzeError, match="Spark returned an invalid analysis"):
        parse_analysis("not json {{{")
    with pytest.raises(AnalyzeError, match="Spark returned an invalid analysis"):
        parse_analysis(json.dumps({"title": "ok", "steps": [{"title": "x"}]}))


def test_respond_400_raises_meta_error_but_deletes_file(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir)
    client, fake = make_client(tmp_path, [status_error(400)])

    with pytest.raises(MetaError):
        run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    assert fake.files.deleted == ["file-abc"]


class RecordingClient:
    """Pipeline-level fake: records the exact respond kwargs."""

    def __init__(self):
        self.respond_kwargs: dict = {}
        self.deleted: list[str] = []

    def upload_file(self, path):
        del path
        return "file-abc"

    def respond(self, **kwargs):
        self.respond_kwargs = kwargs
        return fake_answer()

    def delete_file(self, file_id):
        self.deleted.append(file_id)


def test_analyze_passes_timeout_and_no_retry_timeouts(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir)
    client = RecordingClient()

    run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    assert ANALYZE_TIMEOUT_S == 600.0
    assert client.respond_kwargs["timeout_s"] == 600.0
    assert client.respond_kwargs["retry_timeouts"] is False
    assert client.deleted == ["file-abc"]


def test_analyze_timeout_reaches_responses_create(tmp_path):
    job_dir = tmp_path / "job"
    make_job(job_dir)
    client, fake = make_client(tmp_path, [fake_answer()])

    run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    timeout = fake.responses.kwargs[0]["timeout"]
    assert timeout.read == 600


def test_missing_video_names_it_and_skips_upload(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "ingest.json").write_text(json.dumps({"duration_s": 42.0}), encoding="utf-8")
    client, fake = make_client(tmp_path, [fake_answer()])

    with pytest.raises(AnalyzeError, match="video.mp4"):
        run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    assert fake.files.created == 0
    assert fake.responses.calls == 0


def test_missing_ingest_names_it(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "video.mp4").write_bytes(b"fake-video-bytes")
    client, fake = make_client(tmp_path, [fake_answer()])

    with pytest.raises(AnalyzeError, match="ingest.json"):
        run(job_dir, Settings(model_api_key="", data_dir=tmp_path), client)

    assert fake.files.created == 0
    assert fake.responses.calls == 0
