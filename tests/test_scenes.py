"""Tests for the step-cut stage."""

import json

import pytest

from app.config import Settings
from app.pipeline import scenes
from app.pipeline.scenes import ScenesError, cuts_to_segments, keyword_cuts


def test_keyword_matches_single_forms_only():
    for text in ["Step one", "next step.", "Siguiente PASO", "paso 3"]:
        assert scenes.KEYWORD.search(text), text
    for text in ["steps", "pasó", "footstep"]:
        assert not scenes.KEYWORD.search(text), text


def test_keyword_cuts_drops_close_cuts():
    turns = [
        {"start_s": 1.0, "end_s": 2.0, "text": "step one"},
        {"start_s": 2.0, "end_s": 3.0, "text": "step"},
        {"start_s": 10.0, "end_s": 11.0, "text": "ok"},
        {"start_s": 20.0, "end_s": 21.0, "text": "paso dos"},
    ]
    assert keyword_cuts(turns) == [1.0, 20.0]


def test_cuts_to_segments_merges_short_segment():
    assert cuts_to_segments([5.0, 6.0, 20.0], 30.0) == [
        {"start_s": 5.0, "end_s": 20.0},
        {"start_s": 20.0, "end_s": 30.0},
    ]


def test_cuts_to_segments_empty_and_past_duration():
    assert cuts_to_segments([], 30.0) == []
    assert cuts_to_segments([30.0], 30.0) == []
    assert cuts_to_segments([35.0], 30.0) == []


def test_run_narrated_with_three_keywords(tmp_path):
    settings = _write_job(
        tmp_path,
        turns=[
            {"start_s": 1.2, "end_s": 3.0, "text": "Step one, remove the back panel"},
            {"start_s": 15.0, "end_s": 17.0, "text": "Next step, take out the battery"},
            {"start_s": 30.0, "end_s": 32.0, "text": "Paso tres, lift the board"},
        ],
    )
    result = scenes.run(settings.data_dir, settings)
    assert result["source"] == "voice"
    assert len(result["segments"]) == 3
    assert result["segments"][0]["start_s"] == 1.2
    stored = json.loads((settings.data_dir / "scenes.json").read_text(encoding="utf-8"))
    assert stored == result


def test_run_silent_has_no_segments(tmp_path):
    settings = _write_job(tmp_path, mode="silent", turns=[])
    result = scenes.run(tmp_path, settings)
    assert result["source"] == "none"
    assert result["segments"] == []


def test_run_narrated_with_one_keyword_gives_none(tmp_path):
    settings = _write_job(
        tmp_path,
        turns=[
            {"start_s": 5.0, "end_s": 7.0, "text": "Step one, open the case"},
            {"start_s": 12.0, "end_s": 14.0, "text": "now keep unscrewing"},
        ],
    )
    result = scenes.run(tmp_path, settings)
    assert result["source"] == "none"
    assert result["segments"] == []


def test_run_without_transcript_is_silent(tmp_path):
    # Transcription is optional: if it failed, scenes treats the video as silent.
    settings = Settings(model_api_key="", data_dir=tmp_path)
    (tmp_path / "ingest.json").write_text(
        json.dumps({"duration_s": 42.0, "width": 720, "height": 1280, "has_audio": True}),
        encoding="utf-8",
    )
    result = scenes.run(tmp_path, settings)
    assert result == {"source": "none", "cuts": [], "segments": []}


def test_run_with_broken_transcript_raises(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    (tmp_path / "ingest.json").write_text(json.dumps({"duration_s": 42.0}), encoding="utf-8")
    (tmp_path / "transcript.json").write_text("{", encoding="utf-8")
    with pytest.raises(ScenesError, match="transcript.json"):
        scenes.run(tmp_path, settings)


def _write_job(job_dir, mode="narrated", turns=None, duration=42.0):
    settings = Settings(model_api_key="", data_dir=job_dir)
    (job_dir / "ingest.json").write_text(
        json.dumps({"duration_s": duration, "width": 720, "height": 1280, "has_audio": True}),
        encoding="utf-8",
    )
    (job_dir / "transcript.json").write_text(
        json.dumps(
            {"mode": mode, "duration_s": duration, "transcript": "...", "turns": turns or []}
        ),
        encoding="utf-8",
    )
    return settings
