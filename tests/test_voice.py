"""The voice: text the model can read, one WAV per line, and a clean refusal without the model."""

import types
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import artifacts, voice
from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.routes.upload import settings_dep
from app.schemas import Guide


def _settings(tmp_path, installed=True):
    folder = tmp_path / "model"
    folder.mkdir(exist_ok=True)
    if installed:
        (folder / "model.onnx").write_bytes(b"x")
    return Settings(model_api_key="", data_dir=tmp_path, voice_model_dir=folder)


class FakeEngine:
    def __init__(self):
        self.lines = []

    def generate(self, line, sid=0, speed=1.0):
        self.lines.append(line)
        return types.SimpleNamespace(samples=np.full(1600, 0.5).tolist(), sample_rate=16000)


@pytest.fixture()
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(voice, "_load", lambda settings: fake)
    return fake


def test_numbers_are_spelled_out():
    assert voice.number_words(7) == "seven"
    assert voice.number_words(42) == "forty two"
    assert voice.number_words(305) == "three hundred five"
    assert voice.number_words(1200) == "one thousand two hundred"
    assert voice.number_words(12345) == "one two three four five"


def test_clean_leaves_only_what_the_model_reads():
    assert voice.clean("Remove 4 Screws (M2), don’t bend!") == "remove four screws m two don't bend"
    assert voice.clean("A 3mm bit at 50%") == "a three millimeters bit at fifty percent"
    assert voice.clean("...") == ""


def test_text_is_cut_at_its_stops():
    assert voice.sentences("Lift it. Do not bend it!\nDone") == [
        "lift it",
        "do not bend it",
        "done",
    ]


def test_ready_needs_the_model_and_english(tmp_path):
    assert voice.ready(_settings(tmp_path), "en-US")
    assert not voice.ready(_settings(tmp_path), "es")
    other = tmp_path / "other"
    other.mkdir()
    missing = Settings(model_api_key="", data_dir=other, voice_model_dir=other / "none")
    assert not voice.ready(missing, "en")


def test_speak_makes_a_wav_once_with_a_pause_between_lines(tmp_path, engine):
    settings = _settings(tmp_path)

    first = voice.speak(tmp_path, settings, "Lift it. Do not bend it.")
    again = voice.speak(tmp_path, settings, "Lift it. Do not bend it.")

    assert first == again and engine.lines == ["lift it", "do not bend it"]
    with wave.open(str(first)) as out:
        assert out.getframerate() == 16000
        assert out.getnframes() == 2 * (1600 + int(16000 * voice.PAUSE_S))


def test_speak_refuses_cleanly(tmp_path, engine):
    with pytest.raises(voice.VoiceError):
        voice.speak(tmp_path, _settings(tmp_path), "x" * (voice.MAX_TEXT + 1))
    with pytest.raises(voice.VoiceError):
        voice.speak(tmp_path, _settings(tmp_path), "...")
    (tmp_path / "model" / "model.onnx").unlink()
    with pytest.raises(voice.VoiceError):
        voice.speak(tmp_path, _settings(tmp_path, installed=False), "Hello.")
    assert engine.lines == []


def test_route_returns_audio_or_a_clean_error(tmp_path, engine):
    settings = _settings(tmp_path)
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        job_id = create_job(settings.jobs_dir).job_id
        guide = Guide(
            title="Fix", device="Lamp", mode="silent", language="en", duration_s=60.0, steps=[]
        )
        artifacts.save(settings.jobs_dir / job_id, guide)
        client = TestClient(app)
        good = client.post(f"/api/voice/{job_id}", data={"text": "Lift it."})
        empty = client.post(f"/api/voice/{job_id}", data={"text": "..."})
        unknown = client.post("/api/voice/000000000000", data={"text": "Lift it."})
    finally:
        app.dependency_overrides.pop(settings_dep, None)
    assert good.status_code == 200 and good.headers["content-type"] == "audio/wav"
    assert empty.status_code == 503
    assert unknown.status_code == 404
