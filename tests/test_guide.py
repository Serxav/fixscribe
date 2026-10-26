import json

import pytest
from pydantic import ValidationError

from app.pipeline.guide import GuideError, build_guide, clean_times, run
from app.schemas import Analysis, DraftStep, Guide


def draft(title, start, end, **extra):
    return DraftStep(title=title, start_s=start, end_s=end, **extra)


def analysis(*steps):
    return Analysis(title="Replace battery", device="Phone X", steps=list(steps))


def test_clean_times_clamps_sorts_and_fixes_overlaps():
    drafts = [draft("b", 8, 20), draft("a", -1, 10), draft("c", 25, 99)]
    kept, notes = clean_times(drafts, duration_s=30)
    assert [(d.title, d.start_s, d.end_s) for d in kept] == [
        ("a", 0.0, 10.0),
        ("b", 10.0, 20.0),
        ("c", 25.0, 30.0),
    ]
    assert notes == []


def test_clean_times_drops_steps_with_no_time_left():
    kept, notes = clean_times(
        [draft("a", 0, 10), draft("inside a", 2, 9), draft("late", 40, 50)], 30
    )
    assert [d.title for d in kept] == ["a"]
    assert len(notes) == 2


def test_build_guide_makes_valid_guide_with_reassembly():
    guide = build_guide(
        analysis(
            draft("Remove cover", 0, 10, action="unscrew", removes=["back cover"], screw_count=4),
            draft("Disconnect battery", 10, 20, action="disconnect", removes=["battery connector"]),
        ),
        duration_s=25,
        mode="narrated",
    )
    assert [s.index for s in guide.steps] == [1, 2]
    assert guide.steps[0].screws.count == 4
    assert [r.source_step for r in guide.reassembly] == [2, 1]
    # SAM has not located the screws yet, so the builder says so.
    assert any("4 screws counted but 0 located" in c for c in guide.checks)
    Guide.model_validate(guide.model_dump())  # round-trips


def test_low_confidence_steps_are_flagged():
    guide = build_guide(analysis(draft("a", 0, 5, confidence=0.2)), 10, "silent")
    assert guide.steps[0].review == "needs_review"
    assert any("review steps: 1" in c for c in guide.checks)


def test_empty_instruction_falls_back_to_title():
    guide = build_guide(analysis(draft("Remove SIM tray", 0, 5)), 10, "silent")
    assert guide.steps[0].instruction == "Remove SIM tray"


def test_analysis_ignores_extra_keys_but_checks_types():
    Analysis.model_validate({"steps": [{"title": "a", "start_s": 0, "end_s": 1, "foo": 1}]})
    with pytest.raises(ValidationError):
        Analysis.model_validate({"steps": [{"title": "a", "start_s": "soon", "end_s": 1}]})


def write(folder, name, data):
    (folder / name).write_text(json.dumps(data))


def test_run_writes_guide_json(tmp_path):
    write(tmp_path, "analysis.json", analysis(draft("a", 0, 5)).model_dump())
    write(tmp_path, "ingest.json", {"duration_s": 12.0})
    write(tmp_path, "transcript.json", {"mode": "narrated", "turns": []})
    run(tmp_path, settings=None)
    saved = Guide.model_validate_json((tmp_path / "guide.json").read_text())
    assert saved.mode == "narrated"
    assert saved.duration_s == 12.0


def test_run_without_transcript_is_silent(tmp_path):
    write(tmp_path, "analysis.json", analysis(draft("a", 0, 5)).model_dump())
    write(tmp_path, "ingest.json", {"duration_s": 12.0})
    assert run(tmp_path, settings=None).mode == "silent"


def test_run_fails_clearly(tmp_path):
    with pytest.raises(GuideError, match="analysis.json"):
        run(tmp_path, settings=None)
    write(tmp_path, "analysis.json", {"steps": []})
    write(tmp_path, "ingest.json", {"duration_s": 12.0})
    with pytest.raises(GuideError, match="no repair steps"):
        run(tmp_path, settings=None)
