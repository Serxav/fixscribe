import json

import pytest

from app.schemas import Guide, ScrewMap, Step
from eval.score import format_report, iou, main, match_steps, score

EXPECTED = [
    {"title": "Remove back cover", "start_s": 0.0, "end_s": 10.0, "screws": 4},
    {"title": "Disconnect battery", "start_s": 10.0, "end_s": 20.0},
    {"title": "Remove battery", "start_s": 20.0, "end_s": 30.0, "screws": 2},
]


def step(start, end, screws=0):
    return {"title": "x", "start_s": start, "end_s": end, "screws": screws}


def test_iou():
    assert iou(0, 10, 0, 10) == 1.0
    assert iou(0, 10, 10, 20) == 0.0
    assert iou(0, 10, 5, 15) == pytest.approx(5 / 15)


def test_perfect_guide():
    result = score([step(0, 10, 4), step(10, 20), step(20, 30, 2)], EXPECTED)
    assert result["step_f1"] == 1.0
    assert result["boundary_hit_rate"] == 1.0
    assert result["screw_count_accuracy"] == 1.0


def test_missing_step_lowers_recall_not_precision():
    result = score([step(0, 10, 4), step(20, 30, 2)], EXPECTED)
    assert result["step_precision"] == 1.0
    assert result["step_recall"] == pytest.approx(0.667, abs=0.001)
    assert result["boundary_hit_rate"] == pytest.approx(0.667, abs=0.001)


def test_extra_step_lowers_precision():
    found = [step(0, 10, 4), step(10, 20), step(20, 30, 2), step(30, 40)]
    result = score(found, EXPECTED)
    assert result["step_precision"] == 0.75
    assert result["step_recall"] == 1.0


def test_late_boundaries_and_wrong_screws():
    result = score([step(3, 13, 3), step(13, 20), step(20, 30, 2)], EXPECTED)
    first = result["rows"][0]
    assert first["start_error_s"] == 3.0
    assert not first["boundary_hit"]
    assert result["screw_count_accuracy"] == 0.5


def test_each_step_matched_once():
    # One long found step covers two expected steps: it may match only one of them.
    matches = match_steps([step(0, 20)], EXPECTED)
    assert len(matches) == 1


def test_empty_guide():
    result = score([], EXPECTED)
    assert result["step_f1"] == 0.0
    assert result["mean_start_error_s"] is None
    assert "0 matched" in format_report(result)


def test_cli(tmp_path, capsys):
    guide = Guide(
        title="t",
        device="d",
        mode="silent",
        steps=[
            Step(
                index=1, title="a", instruction="a", start_s=0, end_s=10, screws=ScrewMap(count=4)
            ),
            Step(index=2, title="b", instruction="b", start_s=10, end_s=20),
        ],
    )
    guide_path = tmp_path / "guide.json"
    guide_path.write_text(guide.model_dump_json())
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps({"steps": EXPECTED}))
    assert main([str(guide_path), str(expected_path)]) == 0
    assert "2 matched, 2 found, 3 expected" in capsys.readouterr().out
    assert main([]) == 2
