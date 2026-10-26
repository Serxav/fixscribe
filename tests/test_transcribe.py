"""Transcribe stage tests. The Meta API is faked, never called."""

import json
import wave
from pathlib import Path

from app.config import Settings
from app.pipeline.transcribe import run


def make_settings(data_dir: Path) -> Settings:
    return Settings(model_api_key="test-key", data_dir=data_dir, budget_usd=120.0)


def make_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\0" * 24000 * 2)
    return path


class FakeTranscriber:
    """Fake MetaClient: transcribe returns a canned payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list = []

    def transcribe(self, wav, **kwargs):
        self.calls.append((wav, kwargs))
        return self.payload


def test_run_without_audio_is_silent(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    fake = FakeTranscriber(payload={})

    result = run(job_dir, make_settings(tmp_path), client=fake).model_dump()

    assert fake.calls == []
    assert result == {"mode": "silent", "duration_s": 0.0, "transcript": "", "turns": []}
    with open(job_dir / "transcript.json", encoding="utf-8") as f:
        assert json.load(f) == result


def test_run_converts_turns_to_seconds_sorted(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    make_wav(job_dir / "audio.wav")
    fake = FakeTranscriber(
        payload={
            "sessionId": "sess-1",
            "transcript": "full text",
            "audioDurationMs": 42500,
            "turns": [
                {
                    "turnId": 2,
                    "startMs": 5000,
                    "endMs": 7000,
                    "transcript": "paso dos sigue",
                },
                {"turnId": 3, "startMs": 9000, "endMs": 9500, "transcript": "   "},
                {
                    "turnId": 1,
                    "startMs": 1200,
                    "endMs": 3400,
                    "transcript": "Step one remove the two screws",
                },
            ],
        }
    )

    result = run(job_dir, make_settings(tmp_path), client=fake).model_dump()

    assert len(fake.calls) == 1
    wav, kwargs = fake.calls[0]
    assert wav == job_dir / "audio.wav"
    assert kwargs == {
        "mode": "ENDPOINTING",
        "language_bias": ["Spanish", "English"],
        "keywords": ["step", "paso"],
    }
    assert result["mode"] == "narrated"
    assert result["duration_s"] == 42.5
    assert result["transcript"] == "full text"
    assert result["turns"] == [
        {"start_s": 1.2, "end_s": 3.4, "text": "Step one remove the two screws"},
        {"start_s": 5.0, "end_s": 7.0, "text": "paso dos sigue"},
    ]
    with open(job_dir / "transcript.json", encoding="utf-8") as f:
        assert json.load(f) == result


def test_run_skips_turn_missing_start_ms(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    make_wav(job_dir / "audio.wav")
    fake = FakeTranscriber(
        payload={
            "sessionId": "sess-1",
            "transcript": "full text",
            "audioDurationMs": 42500,
            "turns": [
                {"turnId": 1, "endMs": 3400, "transcript": "missing start"},
                {
                    "turnId": 2,
                    "startMs": 1200,
                    "endMs": 3400,
                    "transcript": "Step one remove the two screws",
                },
            ],
        }
    )

    result = run(job_dir, make_settings(tmp_path), client=fake).model_dump()

    assert result["turns"] == [
        {"start_s": 1.2, "end_s": 3.4, "text": "Step one remove the two screws"}
    ]


def test_run_missing_turns_is_empty(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    make_wav(job_dir / "audio.wav")
    fake = FakeTranscriber(
        payload={"sessionId": "sess-1", "transcript": "", "audioDurationMs": 1000}
    )

    result = run(job_dir, make_settings(tmp_path), client=fake).model_dump()

    assert result["turns"] == []


def test_run_single_short_turn_is_silent(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    make_wav(job_dir / "audio.wav")
    fake = FakeTranscriber(
        payload={
            "sessionId": "sess-2",
            "transcript": "ok thanks",
            "audioDurationMs": 3000,
            "turns": [{"turnId": 1, "startMs": 500, "endMs": 1500, "transcript": "ok thanks"}],
        }
    )

    result = run(job_dir, make_settings(tmp_path), client=fake).model_dump()

    assert result["mode"] == "silent"
    assert result["duration_s"] == 3.0
    assert result["turns"] == [{"start_s": 0.5, "end_s": 1.5, "text": "ok thanks"}]
    with open(job_dir / "transcript.json", encoding="utf-8") as f:
        assert json.load(f) == result
