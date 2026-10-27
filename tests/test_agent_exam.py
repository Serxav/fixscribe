import json

import pytest

from app.agent import record
from app.agent.record import Act, AgentRecord, AgentStep, Observe, Part, Turn
from eval.agent_exam import box_iou, grade, load_key, main, match_parts, report


def key() -> dict:
    return {
        "video": "ikea-table",
        "parts": [
            {
                "name": "metal bolt",
                "aliases": ["bolt", "screw", "long bolt"],
                "count": 4,
                "t_s": 12.0,
                "box": [410, 520, 470, 610],
            },
            {"name": "table leg", "aliases": ["leg"], "count": 4, "t_s": 20.0, "box": None},
        ],
        "steps": [
            {
                "action": "insert",
                "parts": ["metal bolt", "table leg"],
                "start_s": 10.0,
                "end_s": 25.0,
            }
        ],
    }


def perfect_record() -> AgentRecord:
    return AgentRecord(
        status="running",
        usd=0.0123,
        parts=[
            Part(id="A", name="metal bolt", count=4, t_s=12.0, box=(410, 520, 470, 610)),
            Part(id="B", name="table leg", count=4, t_s=20.0),
        ],
        steps=[
            AgentStep(
                n=1,
                action="insert",
                text="Insert the bolts",
                parts=["A", "B"],
                start_s=10.0,
                end_s=25.0,
                verified=True,
            )
        ],
    )


def test_perfect_run_scores_100():
    result = grade(perfect_record(), key())
    assert result["grade"] == 100
    assert result["parts_found"] == result["parts_expected"] == 2
    assert result["count_right"] == 2
    assert (result["place_right"], result["place_checkable"]) == (1, 1)
    assert result["steps_found"] == result["steps_expected"] == 1
    assert result["action_right"] == 1
    assert result["parts_right"] == 1
    assert result["order_right"] is True
    assert result["verified_share"] == 1.0
    assert "Missed parts: none" in report(result)


def test_alias_and_all_words_matches():
    assert ("A", "metal bolt") in match_parts([Part(id="A", name="Bolt!")], key()["parts"][:1])
    assert ("B", "metal bolt") in match_parts(
        [Part(id="B", name="long metal bolt")], key()["parts"][:1]
    )


def test_each_part_used_once_and_extra_part():
    rec = perfect_record()
    rec.parts.append(Part(id="C", name="Bolt", count=1))
    result = grade(rec, key())
    assert result["parts_extra"] == 1
    assert result["parts_found"] == 2
    assert "extra 1" in report(result)


def test_count_wrong():
    rec = perfect_record()
    rec.parts[0].count = 3
    assert grade(rec, key())["count_right"] == 1


def test_box_iou_pass_and_fail():
    assert box_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert box_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    rec = perfect_record()
    rec.parts[0].box = (700, 700, 760, 790)
    result = grade(rec, key())
    assert (result["place_right"], result["place_checkable"]) == (0, 1)
    assert result["grade"] < 100


def test_time_too_far_is_not_checkable():
    rec = perfect_record()
    rec.parts[0].t_s = 30.0
    result = grade(rec, key())
    assert result["place_checkable"] == 0
    assert result["place_right"] == 0
    assert result["grade"] == 100


def test_missed_step():
    rec = perfect_record()
    rec.steps = []
    result = grade(rec, key())
    assert result["steps_found"] == 0
    assert result["steps_extra"] == 0
    assert result["verified_share"] == 0.0
    assert "Missed steps (times)" in report(result)
    assert "insert" in report(result)


def test_wrong_order():
    two = {
        "video": "v",
        "parts": [],
        "steps": [
            {"action": "open", "parts": [], "start_s": 0.0, "end_s": 10.0},
            {"action": "remove", "parts": [], "start_s": 30.0, "end_s": 40.0},
        ],
    }
    rec = AgentRecord(
        status="running",
        steps=[
            AgentStep(n=1, action="remove", text="take it out", start_s=30.0, end_s=40.0),
            AgentStep(n=2, action="open", text="open it", start_s=0.0, end_s=10.0),
        ],
    )
    result = grade(rec, two)
    assert result["steps_found"] == 2
    assert result["order_right"] is False
    assert result["grade"] < 100


def test_step_parts_use_letter_mapping():
    rec = perfect_record()
    rec.steps[0].parts = ["A"]
    result = grade(rec, key())
    assert result["action_right"] == 1
    assert result["parts_right"] == 0


def test_turns_count_questions_refusals_and_cost():
    rec = perfect_record()
    turns = [
        Turn(turn=1, act=Act(tool="look", args={}), observe=Observe(ok=True, text="ok")),
        Turn(turn=2, act=Act(tool="ask_person", args={}), observe=Observe(ok=True, text="q")),
        Turn(turn=3, act=Act(tool="look", args={}), observe=Observe(ok=False, text="no")),
    ]
    result = grade(rec, key(), turns)
    assert result["questions_asked"] == 1
    assert result["refusals"] == 1
    assert result["turns"] == 3
    assert result["usd"] == pytest.approx(0.0123)


def test_load_key_rejects_bad_keys(tmp_path):
    good = tmp_path / "key.json"
    good.write_text(json.dumps(key()))
    assert load_key(good)["parts"][0]["name"] == "metal bolt"
    bad_cases = [
        {"steps": []},
        {"parts": [], "steps": {}},
        {"parts": [{"name": "", "count": 1, "t_s": 0.0}], "steps": []},
        {"parts": [{"name": "x", "count": 0, "t_s": 0.0}], "steps": []},
        {"parts": [{"name": "x", "count": 1, "t_s": 0.0, "box": [1, 2, 3]}], "steps": []},
        {"parts": [], "steps": [{"action": "insert", "parts": [], "start_s": 5.0, "end_s": 5.0}]},
    ]
    for pos, bad in enumerate(bad_cases):
        path = tmp_path / f"bad{pos}.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            load_key(path)
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError):
        load_key(missing)


def test_main_on_idle_job_returns_1(tmp_path, capsys):
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps(key()))
    assert main([str(tmp_path / "job"), str(key_path)]) == 1
    assert "no agent record" in capsys.readouterr().out


def test_main_bad_usage_returns_2(capsys):
    assert main([]) == 2
    assert "usage" in capsys.readouterr().out


def test_main_writes_exam_json(tmp_path, capsys):
    job = tmp_path / "job"
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps(key()))
    record.save_record(job, perfect_record())
    assert main([str(job), str(key_path)]) == 0
    out = capsys.readouterr().out
    assert "# Agent exam: 100/100" in out
    saved = json.loads((job / "agent" / "exam.json").read_text())
    assert saved["grade"] == 100
    assert saved["parts_found"] == 2
