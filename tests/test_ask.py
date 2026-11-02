"""Ask the coach out loud: the words that need no AI, questions, and bad clips. Meta is mocked."""

import io
import wave

import pytest
from fastapi.testclient import TestClient

from app import artifacts, meta_client, spark
from app.config import Settings
from app.jobs import create_job
from app.main import app
from app.meta_client import MetaError
from app.pipeline.ask import (
    build_prompt,
    check_clip,
    live_typed,
    live_voice,
    parse_command,
    proof_second,
)
from app.pipeline.live import LiveError
from app.routes.upload import settings_dep
from app.schemas import Guide, Safety, Step


def _clip(rate=16000, channels=1, seconds=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\0\0" * channels * rate * seconds)
    return out.getvalue()


def _guide(**overrides):
    step = Step(
        index=1,
        title="Open",
        instruction="Open the cover.",
        warnings=["Battery can burn."],
        start_s=0,
        end_s=5,
    )
    return Guide(
        title="Fix", device="Phone", language="en", mode="silent", steps=[step], **overrides
    )


class Ears:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.bias = None

    def transcribe(self, path, language_bias=None, keywords=None):
        self.bias = language_bias
        self.keywords = keywords
        if self.error:
            raise self.error
        return {"transcript": self.text}


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("Next step.", "next"),
        ("¡Siguiente!", "next"),
        ("go back", "back"),
        ("Atrás", "back"),
        ("Repítelo", "repeat"),
        ("otra vez", "repeat"),
        ("be quiet", "quiet"),
        ("What's the next tool?", "question"),
        ("¿Dónde va este tornillo?", "question"),
        ("I think next time I will bring the other one", "none"),
        ("hmm okay", "none"),
        ("", "none"),
    ],
)
def test_parse_command(text, command):
    assert parse_command(text) == command


def test_good_clips_pass_and_bad_clips_are_refused():
    check_clip(_clip())
    check_clip(_clip(rate=24000))
    for bad in (b"", b"not a wav", _clip(rate=44100), _clip(channels=2), _clip(seconds=9)):
        with pytest.raises(LiveError):
            check_clip(bad)


def test_a_command_needs_no_ai(tmp_path, monkeypatch):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()

    def no_spark(*_, **__):
        raise AssertionError("a command must not call Spark")

    monkeypatch.setattr(spark, "ask_json", no_spark)
    ears = Ears("siguiente")
    heard = live_voice(tmp_path, Settings(model_api_key=""), _clip(), 1, b"", ears)

    assert (heard.command, heard.heard, heard.answer) == ("next", "siguiente", "")
    assert ears.bias == ["Spanish", "English"]
    assert "go back" in ears.keywords


def test_muttering_does_nothing(tmp_path):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()

    heard = live_voice(tmp_path, Settings(model_api_key=""), _clip(), 1, b"", Ears("hmm okay"))

    assert heard.command == "none"


def test_a_question_is_answered_from_the_guide(tmp_path, monkeypatch):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()
    asked = {}

    def fake_ask(client, settings, **kwargs):
        asked.update(kwargs)
        return {"answer": "Step 1: open the cover.", "step": 1}

    monkeypatch.setattr(spark, "ask_json", fake_ask)
    heard = live_voice(
        tmp_path, Settings(model_api_key=""), _clip(), 1, b"", Ears("What do I open?")
    )

    assert heard.command == "question"
    assert heard.answer == "Step 1: open the cover."
    assert (heard.see_step, heard.see_s) == (1, 0)
    assert "What do I open?" in asked["prompt"]
    assert "Battery can burn." in asked["prompt"]
    assert asked["images"] == []


@pytest.mark.parametrize("step", [0, 7, "1", None])
def test_an_answer_from_no_known_step_points_nowhere(tmp_path, monkeypatch, step):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()
    monkeypatch.setattr(spark, "ask_json", lambda *a, **k: {"answer": "Cannot tell.", "step": step})

    heard = live_voice(tmp_path, Settings(model_api_key=""), _clip(), 1, b"", Ears("Where is it?"))

    assert (heard.answer, heard.see_step, heard.see_s) == ("Cannot tell.", 0, None)


def test_proof_second_prefers_the_sharpest_frame():
    guide = _guide()
    assert proof_second(guide, 1) == 0
    guide.steps[0].keyframe_s = 3.5
    assert proof_second(guide, 1) == 3.5
    assert proof_second(guide, 2) is None


def test_a_professional_job_gets_no_instructions(tmp_path, monkeypatch):
    safety = Safety(level="professional_only", reasons=["Mains panel: call an electrician."])
    artifacts.save(tmp_path, _guide(safety=safety))
    (tmp_path / "live").mkdir()

    def no_spark(*_, **__):
        raise AssertionError("no instructions for a professional job")

    monkeypatch.setattr(spark, "ask_json", no_spark)
    ears = Ears("How do I open it?")
    heard = live_voice(tmp_path, Settings(model_api_key=""), _clip(), 1, b"", ears)

    assert heard.answer == "Mains panel: call an electrician."


def test_failed_transcription_is_a_clear_error(tmp_path):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()

    with pytest.raises(LiveError, match="could not hear"):
        live_voice(
            tmp_path, Settings(model_api_key=""), _clip(), 1, b"", Ears(error=MetaError("x"))
        )


def test_prompt_keeps_a_quote_from_breaking_the_question():
    assert "'odd'" in build_prompt(_guide(), 1, 'an "odd" one')


def test_route_hears_a_clip_and_refuses_bad_ones(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(meta_client, "_factory", lambda *args, **kwargs: Ears("next"))
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    try:
        status = create_job(data_dir / "jobs")
        artifacts.save(data_dir / "jobs" / status.job_id, _guide())
        client = TestClient(app)
        good = {"audio": ("voice.wav", _clip(), "audio/wav")}
        url = f"/api/live/{status.job_id}/hear"

        response = client.post(url, files=good, data={"step": "1"})
        assert response.status_code == 200
        assert response.json()["command"] == "next"

        bad = {"audio": ("voice.wav", b"nope", "audio/wav")}
        assert client.post(url, files=bad).status_code == 400
        assert client.post("/api/live/nope/hear", files=good).status_code == 404
    finally:
        app.dependency_overrides.pop(settings_dep, None)


def test_a_typed_line_is_a_question_without_transcription(tmp_path, monkeypatch):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()
    asked = {}

    def fake_ask(client, settings, **kwargs):
        asked.update(kwargs)
        return {"answer": "Step 1 opens the cover.", "step": 1}

    monkeypatch.setattr(spark, "ask_json", fake_ask)
    ears = Ears(error=AssertionError("typing needs no transcription"))
    heard = live_typed(tmp_path, Settings(model_api_key=""), "  the cover is stuck  ", 1, b"", ears)

    assert (heard.command, heard.heard, heard.see_step) == ("question", "the cover is stuck", 1)
    assert "the cover is stuck" in asked["prompt"]


def test_a_typed_command_needs_no_model(tmp_path, monkeypatch):
    artifacts.save(tmp_path, _guide())
    monkeypatch.setattr(spark, "ask_json", lambda *a, **k: pytest.fail("no Spark for a command"))
    settings = Settings(model_api_key="")

    assert live_typed(tmp_path, settings, "next", 1).command == "next"
    assert live_typed(tmp_path, settings, "hmm", 1).command == "none"
    with pytest.raises(LiveError, match="empty"):
        live_typed(tmp_path, settings, "   ", 1)


def test_route_answers_a_typed_question(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(meta_client, "_factory", lambda *args, **kwargs: Ears())
    monkeypatch.setattr(spark, "ask_json", lambda *a, **k: {"answer": "Lift it.", "step": 1})
    app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=data_dir)
    try:
        status = create_job(data_dir / "jobs")
        artifacts.save(data_dir / "jobs" / status.job_id, _guide())
        client = TestClient(app)
        url = f"/api/live/{status.job_id}/ask"

        response = client.post(url, data={"text": "how do I open it", "step": "1"})
        assert response.status_code == 200
        assert response.json()["answer"] == "Lift it."
        assert response.json()["see_s"] == 0
        assert client.post(url, data={"text": " "}).status_code == 400
        assert client.post("/api/live/nope/ask", data={"text": "hi there"}).status_code == 404
    finally:
        app.dependency_overrides.pop(settings_dep, None)


def test_a_short_typed_question_with_a_command_word_is_still_a_question(tmp_path, monkeypatch):
    artifacts.save(tmp_path, _guide())
    (tmp_path / "live").mkdir()
    monkeypatch.setattr(spark, "ask_json", lambda *a, **k: {"answer": "Heat it.", "step": 1})
    settings = Settings(model_api_key="", data_dir=tmp_path)

    heard = live_typed(tmp_path, settings, "back cover stuck?", 1, b"", Ears())
    assert (heard.command, heard.answer) == ("question", "Heat it.")
    assert live_typed(tmp_path, settings, "Go back", 1).command == "back"
