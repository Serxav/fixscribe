"""Identify stage tests. Everything uses fakes, never the network."""

import json
import types

import pytest
from PIL import Image

from app import artifacts
from app.config import Settings
from app.pipeline import identify, ingest
from app.pipeline.identify import (
    IDENTIFY_TIMEOUT_S,
    MAX_OUTPUT_TOKENS,
    MAX_TRANSCRIPT_CHARS,
    N_FRAMES,
    IdentifyError,
    build_input,
    build_prompt,
    frame_times,
    parse_identity,
    run,
)
from app.schemas import Identity, IngestInfo, Transcript
from tests.video_factory import make_video

ANSWER = {
    "object_name": "front-loading washing machine",
    "category": "appliance",
    "brand": "Bosch",
    "model": "",
    "task": "repair",
    "problem": "drum does not spin",
    "hazards": ["mains_voltage", "pressurized_water", "heavy_part"],
    "skill": "intermediate",
    "language": "en",
    "evidence": ["logo 'Bosch' on the door at frame 2"],
    "confidence": 0.8,
}


class FakeIdentifyClient:
    """Pipeline-level fake: records the exact respond kwargs."""

    def __init__(self, answer: str):
        self.answer = answer
        self.respond_kwargs: dict = {}
        self.calls = 0

    def respond(self, **kwargs):
        self.calls += 1
        self.respond_kwargs = kwargs
        return types.SimpleNamespace(output_text=self.answer)


def _make_job(tmp_path, *, transcript_text=None):
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True, exist_ok=True)
    make_video(job_dir / "original.mp4", size=(360, 640), seconds=3, audio=False)
    settings = Settings(model_api_key="", data_dir=tmp_path)
    ingest.run(job_dir, settings)
    if transcript_text is not None:
        artifacts.save(
            job_dir,
            Transcript(mode="narrated", duration_s=3.0, transcript=transcript_text, turns=[]),
        )
    return job_dir, settings


def _content_blocks(client):
    assert client.calls == 1
    messages = client.respond_kwargs["input"]
    assert len(messages) == 1
    return messages[0]["content"]


def test_frame_times_spread_inside_video():
    assert frame_times(100) == pytest.approx([10.0, 36.67, 63.33, 90.0], abs=0.01)
    assert len(frame_times(60)) == N_FRAMES == 4


def test_frame_times_single_is_middle():
    assert frame_times(10, 1) == [5.0]


def test_frame_times_bad_duration_raises():
    with pytest.raises(ValueError):
        frame_times(0)
    with pytest.raises(ValueError):
        frame_times(-3.0)


def test_build_prompt_empty_means_no_speech():
    prompt = build_prompt("")
    assert "(no speech)" in prompt
    assert "<<TRANSCRIPT>>" not in prompt


def test_build_prompt_cuts_long_transcript():
    prompt = build_prompt("x" * 5000)
    assert "x" * MAX_TRANSCRIPT_CHARS in prompt
    assert "x" * (MAX_TRANSCRIPT_CHARS + 1) not in prompt
    assert MAX_TRANSCRIPT_CHARS == 1500


def test_build_input_text_first_then_images(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"still_{index}.png"
        Image.new("RGB", (8, 8), (index * 40, 0, 0)).save(path)
        paths.append(path)
    result = build_input("look at this", paths)
    assert len(result) == 1
    text_block, *image_blocks = result[0]["content"]
    assert text_block == {"type": "input_text", "text": "look at this"}
    assert len(image_blocks) == 2
    for block in image_blocks:
        assert block["type"] == "input_image"
        assert block["image_url"].startswith("data:image/png;base64,")


def test_run_writes_identity_and_cleans_stills(tmp_path):
    job_dir, settings = _make_job(tmp_path, transcript_text="Step one, open the door")
    client = FakeIdentifyClient(json.dumps(ANSWER))

    result = run(job_dir, settings, client)

    assert isinstance(result, Identity)
    assert artifacts.load(job_dir, Identity) == result
    assert result.object_name == "front-loading washing machine"
    blocks = _content_blocks(client)
    assert blocks[0]["type"] == "input_text"
    assert len(blocks) - 1 == N_FRAMES
    assert all(block["type"] == "input_image" for block in blocks[1:])
    assert client.respond_kwargs["model"] == settings.spark_model
    assert client.respond_kwargs["max_output_tokens"] == MAX_OUTPUT_TOKENS == 4000
    assert client.respond_kwargs["timeout_s"] == IDENTIFY_TIMEOUT_S == 120.0
    assert client.respond_kwargs["text"]["format"]["strict"] is True
    assert not (job_dir / "identify").exists()
    assert (job_dir / "identify_raw.txt").is_file()


def test_run_invalid_json_raises_but_keeps_raw_and_cleans(tmp_path):
    job_dir, settings = _make_job(tmp_path)
    client = FakeIdentifyClient("not json {{{")

    with pytest.raises(IdentifyError, match="Spark returned an invalid identity"):
        run(job_dir, settings, client)

    assert (job_dir / "identify_raw.txt").read_text(encoding="utf-8") == "not json {{{"
    assert not (job_dir / "identify").exists()
    assert not (job_dir / "identity.json").exists()


def test_run_missing_source_raises(tmp_path):
    job_dir, settings = _make_job(tmp_path)
    info = artifacts.load(job_dir, IngestInfo)
    info.source = None
    artifacts.save(job_dir, info)

    with pytest.raises(IdentifyError, match="ingest has no source info"):
        run(job_dir, settings, FakeIdentifyClient(json.dumps(ANSWER)))

    assert not (job_dir / "identify").exists()


def test_parse_identity_rejects_invalid():
    with pytest.raises(IdentifyError, match="Spark returned an invalid identity"):
        parse_identity("")
    with pytest.raises(IdentifyError, match="Spark returned an invalid identity"):
        parse_identity("not json {{{")
    with pytest.raises(IdentifyError, match="Spark returned an invalid identity"):
        parse_identity(json.dumps({"object_name": "x"}))


def test_confidence_percentage_becomes_ratio():
    assert identify.MAX_OUTPUT_TOKENS >= 4000
    parsed = parse_identity(json.dumps({**ANSWER, "confidence": 85}))
    assert parsed.confidence == pytest.approx(0.85)


def test_spoken_text_falls_back_to_turns():
    from app.pipeline.identify import spoken_text
    from app.schemas import Transcript

    turns = [
        {"start_s": 0, "end_s": 1, "text": "hola"},
        {"start_s": 1, "end_s": 2, "text": "lavadora"},
    ]
    assert spoken_text(Transcript(mode="narrated", turns=turns)) == "hola lavadora"
    assert spoken_text(Transcript(mode="narrated", transcript="full", turns=turns)) == "full"
    assert spoken_text(None) == ""
