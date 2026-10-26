"""Tests for the boundary-fusion stage."""

import json

import pytest

from app import artifacts
from app.config import Settings
from app.pipeline import fusion
from app.pipeline.fusion import FusionError, fuse
from app.schemas import Analysis, Candidate, DraftStep, Scenes, Segment, Signals


def _analysis(steps):
    return Analysis(
        steps=[
            DraftStep(title=f"Step {i + 1}", start_s=s[0], end_s=s[1], confidence=s[2])
            for i, s in enumerate(steps)
        ]
    )


def _scenes(cuts, intervals=None):
    return Scenes(
        source="voice" if cuts else "none",
        cuts=list(cuts),
        cut_intervals=[Segment(start_s=a, end_s=b) for a, b in (intervals or [])],
        segments=[],
    )


def _signals(pauses=(), scenes=()):
    candidates = [Candidate(t=t, kind="pause", score=s) for t, s in pauses]
    candidates += [Candidate(t=t, kind="scene", score=s) for t, s in scenes]
    return Signals(fps=4.0, duration_s=60.0, motion=[], scene=[], candidates=candidates)


def test_voice_beats_pause_for_start():
    result = fuse(
        _analysis([(10.4, 20.0, 0.9)]),
        _scenes([10.0], intervals=[(9.5, 10.0)]),
        _signals(pauses=[(10.3, 1.0)]),
    )
    step = result.steps[0]
    assert step.start_s == 10.0
    assert step.start_source == "voice"


def test_pause_two_seconds_away_does_not_snap():
    result = fuse(
        _analysis([(5.0, 15.0, 0.9)]),
        None,
        _signals(pauses=[(7.0, 1.0)]),
    )
    step = result.steps[0]
    assert step.start_s == 5.0
    assert step.start_source == "spark"
    assert step.agreement == 0.6
    assert step.confidence == 0.54


def test_adjacent_steps_share_one_candidate():
    result = fuse(
        _analysis([(0.0, 10.0, 0.9), (10.0, 20.0, 0.9)]),
        None,
        _signals(pauses=[(10.5, 1.0)]),
    )
    assert result.steps[0].end_s == 10.5
    assert result.steps[1].start_s == 10.5
    assert result.steps[0].end_source == "pause"
    assert result.steps[1].start_source == "pause"


def test_snap_that_inverts_step_is_refused():
    # Voice snaps the start forward to 10.9; the pause at 10.5 would invert the end.
    result = fuse(
        _analysis([(10.4, 11.0, 0.9)]),
        _scenes([10.9], intervals=[(10.9, 11.4)]),
        _signals(pauses=[(10.5, 1.0)]),
    )
    step = result.steps[0]
    assert step.start_s == 10.9
    assert step.end_s == 11.0
    assert step.end_source == "spark"
    assert step.end_s > step.start_s


def test_no_candidates_keeps_times_and_confidence():
    result = fuse(_analysis([(5.0, 15.0, 0.8), (15.0, 25.0, 0.7)]), None, None)
    assert result.candidates == 0
    assert [(s.start_s, s.end_s) for s in result.steps] == [(5.0, 15.0), (15.0, 25.0)]
    assert [s.confidence for s in result.steps] == [0.8, 0.7]
    assert all(s.agreement == 1.0 for s in result.steps)


def test_voice_interval_snap_inside_interval():
    result = fuse(
        _analysis([(11.2, 20.0, 0.9)]),
        _scenes([9.0], intervals=[(9.0, 12.0)]),
        None,
    )
    step = result.steps[0]
    assert step.start_s == 11.2
    assert step.start_source == "voice"
    assert step.start_shift_s == 0.0


def test_run_writes_fusion_and_does_not_touch_analysis(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _analysis([(10.4, 20.0, 0.9)]))
    artifacts.save(tmp_path, _scenes([10.0], intervals=[(9.5, 10.0)]))
    artifacts.save(tmp_path, _signals(pauses=[(10.3, 1.0)]))
    before = (tmp_path / "analysis.json").read_bytes()
    result = fusion.run(tmp_path, settings)
    assert result.steps[0].start_s == 10.0
    assert (tmp_path / "analysis.json").read_bytes() == before
    stored = json.loads((tmp_path / "fusion.json").read_text(encoding="utf-8"))
    assert stored == result.model_dump(mode="json")
    assert stored["candidates"] == 2


def test_run_missing_analysis_raises(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    with pytest.raises(FusionError, match="missing analysis.json"):
        fusion.run(tmp_path, settings)


def test_run_broken_analysis_raises(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    (tmp_path / "analysis.json").write_text("{", encoding="utf-8")
    with pytest.raises(FusionError, match="broken analysis.json"):
        fusion.run(tmp_path, settings)


def test_run_without_optional_inputs_keeps_steps(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _analysis([(5.0, 15.0, 0.8)]))
    result = fusion.run(tmp_path, settings)
    assert result.candidates == 0
    assert result.steps[0].start_s == 5.0
    assert result.steps[0].confidence == 0.8


def test_agreement_comes_from_the_start_boundary():
    # Start confirmed by the voice, end with no evidence (the end of the video): full agreement.
    result = fuse(
        _analysis([(10.4, 60.0, 0.9)]),
        _scenes([10.0], intervals=[(9.5, 10.0)]),
        _signals(),
    )
    step = result.steps[0]
    assert (step.start_source, step.end_source) == ("voice", "spark")
    assert step.agreement == 1.0
    assert step.confidence == 0.9
