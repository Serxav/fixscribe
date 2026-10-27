"""A full rehearsal of the agent with a scripted Wonder, a fake Spark pointer and a fake SAM.

No Meta call is made. The script plays a good run: catalog, steps, one question to the person,
the answer, the guide, the sign-off. Other tests play the refusals the tools must give.
"""

import json
import types

import cv2
import numpy as np
import pytest

from app import artifacts
from app.agent import loop
from app.agent import record as rec
from app.agent.record import SignOff
from app.agent.tools import Case, add_part, add_step, normalize, submit_guide, valid_box
from app.config import Settings
from app.meta_client import BudgetExceeded, Detection
from app.schemas import Identity, IngestInfo, Transcript, Turn


def make_job(tmp_path, narrated=True):
    job = tmp_path / "job"
    job.mkdir()
    writer = cv2.VideoWriter(
        str(job / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240)
    )
    for i in range(100):  # 10 s: a white square that moves right
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        x = 20 + i * 2
        frame[100:140, x : x + 40] = 255
        writer.write(frame)
    writer.release()
    artifacts.save(job, IngestInfo(duration_s=10.0, width=320, height=240, has_audio=narrated))
    artifacts.save(
        job,
        Identity(object_name="side table", category="furniture", task="assemble"),
    )
    turns = [Turn(start_s=1.0, end_s=4.0, text="Ahora metemos el tornillo en la pata.")]
    artifacts.save(
        job,
        Transcript(mode="narrated" if narrated else "silent", turns=turns if narrated else []),
    )
    return job


class FakeMeta:
    """Plays Wonder from a script, and answers ground / segment_boxes like Spark and SAM."""

    def __init__(self, script, sam_fill=1.0):
        self.script = list(script)
        self.calls = []
        self.sam_fill = sam_fill
        self.deleted = []

    def upload_file(self, path):
        return "file-1"

    def delete_file(self, file_id):
        self.deleted.append(file_id)

    def respond(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("the script ran out")
        name, args = self.script.pop(0)
        n = len(self.calls)
        output = []
        if name:
            output = [
                types.SimpleNamespace(
                    type="function_call", name=name, arguments=json.dumps(args), call_id=f"c{n}"
                )
            ]
        usage = types.SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            input_tokens_details=types.SimpleNamespace(cached_tokens=0),
        )
        return types.SimpleNamespace(id=f"r{n}", output=output, output_text=f"why {n}", usage=usage)

    def ground(self, image_path, query, *, context="", max_boxes=8):
        return [types.SimpleNamespace(label=query, box=(100, 400, 300, 600), why="the bright one")]

    def segment_boxes(self, image_path, boxes):
        w, h = 32, 24
        filled = int(w * h * self.sam_fill)
        mask = bytes([1] * filled + [0] * (w * h - filled))
        det = Detection(
            "1", (32.0, 96.0, 96.0, 144.0), 0.9, mask, (w, h), (32.0, 96.0, 96.0, 144.0)
        )
        return [det], (320, 240)


GOOD_RUN = [
    ("look", {"t_s": 2.0}),
    ("point", {"frame": "frames/t2.0.jpg", "query": "metal bolt"}),
    (
        "add_part",
        {
            "id": "A",
            "name": "metal bolt",
            "count": 4,
            "frame": "frames/t2.0.jpg",
            "box": [100, 400, 300, 600],
        },
    ),
    (None, {}),  # a turn with only text: the loop reminds it to use a tool
    ("look", {"t_s": 4.0}),
    (
        "ask_person",
        {
            "text": "Is this the long bolt?",
            "frame": "frames/t4.0.jpg",
            "box": [100, 400, 300, 600],
            "options": ["yes", "no"],
        },
    ),
]
AFTER_ANSWER = [
    (
        "add_step",
        {
            "n": 1,
            "action": "insert",
            "text": "Mete el tornillo A en la pata.",
            "parts": ["A"],
            "start_s": 1.0,
            "end_s": 4.0,
            "frame": "frames/t4.0.jpg",
            "to_box": [120, 380, 320, 620],
            "quote": "metemos el tornillo en la pata",
        },
    ),
    ("submit_guide", {}),
]


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


def test_rehearsal_good_run_end_to_end(tmp_path, settings):
    job = make_job(tmp_path)
    meta = FakeMeta(GOOD_RUN + AFTER_ANSWER)

    record = loop.run(job, settings, client=meta)
    assert record.status == "needs_input"
    assert record.question.text == "Is this the long bolt?"
    assert record.parts[0].verified and (job / "agent" / record.parts[0].crop).exists()
    assert meta.calls[0]["model"] == settings.wonder_model
    assert meta.calls[0]["parallel_tool_calls"] is False
    assert "previous_response_id" not in meta.calls[0]
    assert meta.calls[1]["previous_response_id"] == "r1"
    # look -> the next input carries the frame as an image in a user message
    second = meta.calls[1]["input"]
    assert second[0]["type"] == "function_call_output"
    assert second[1]["content"][1]["type"] == "input_image"

    # resume with nothing answered does nothing
    assert loop.run(job, settings, resume=True, client=meta).status == "needs_input"

    rec.write_answer(job, "yes")
    record = loop.run(job, settings, resume=True, client=meta)
    assert record.status == "awaiting_signoff"
    answer_turn = meta.calls[6]["input"][0]
    assert answer_turn == {
        "type": "function_call_output",
        "call_id": "c6",
        "output": "The person answered: yes",
    }
    assert record.steps[0].verified and "quote found in the narration" in record.steps[0].evidence

    rec.write_signoff(job, SignOff(approved=True))
    record = loop.run(job, settings, resume=True, client=meta)
    assert record.status == "done"
    assert meta.deleted == ["file-1"]

    turns = rec.load_turns(job)
    assert [t.turn for t in turns] == list(range(1, 9))
    assert turns[3].act is None  # the text-only turn is still logged
    assert record.usd > 0


def test_rejected_signoff_sends_notes_back(tmp_path, settings):
    job = make_job(tmp_path)
    meta = FakeMeta(GOOD_RUN + AFTER_ANSWER + [("submit_guide", {})])
    loop.run(job, settings, client=meta)
    rec.write_answer(job, "yes")
    loop.run(job, settings, resume=True, client=meta)
    rec.write_signoff(job, SignOff(approved=False, notes="say how tight"))
    record = loop.run(job, settings, resume=True, client=meta)
    assert "say how tight" in meta.calls[-1]["input"][0]["output"]
    assert record.status == "awaiting_signoff"


def test_turn_limit_pauses_and_resume_adds_turns(tmp_path, settings, monkeypatch):
    monkeypatch.setattr(loop, "MAX_TURNS", 2)
    job = make_job(tmp_path)
    meta = FakeMeta([("look", {"t_s": 1.0}), ("look", {"t_s": 2.0}), ("look", {"t_s": 3.0})])
    record = loop.run(job, settings, client=meta)
    assert record.status == "paused" and record.turn == 2
    assert "last turn" in meta.calls[1]["input"][-1]["content"]
    monkeypatch.setattr(loop, "MORE_TURNS", 1)
    record = loop.run(job, settings, resume=True, client=FakeMeta([("look", {"t_s": 5.0})]))
    assert record.status == "paused" and record.turn == 3
    assert record.max_turns == 2 + loop.MORE_TURNS


def test_budget_pauses_without_losing_the_record(tmp_path, settings):
    job = make_job(tmp_path)
    meta = FakeMeta([("look", {"t_s": 1.0})])
    original = meta.respond

    def respond(**kwargs):
        if len(meta.calls) >= 1:
            raise BudgetExceeded("limit")
        return original(**kwargs)

    meta.respond = respond
    record = loop.run(job, settings, client=meta)
    assert record.status == "paused" and "budget" in record.notes[-1]
    assert rec.load_record(job).turn == 1


def test_bad_tool_calls_are_refusals_not_crashes(tmp_path, settings, monkeypatch):
    job = make_job(tmp_path)
    meta = FakeMeta(
        [
            ("teleport", {}),
            ("look", {"t_s": 99}),
            (
                "add_part",
                {
                    "id": "A",
                    "name": "x",
                    "count": 1,
                    "frame": "frames/t5.0.jpg",
                    "box": [0, 0, 10, 10],
                },
            ),
            ("add_step", {"oops": 1}),
            ("submit_guide", {}),
        ]
    )
    monkeypatch.setattr(loop, "MAX_TURNS", 5)
    record = loop.run(job, settings, client=meta)
    observed = [t.observe for t in rec.load_turns(job)]
    assert [o.ok for o in observed] == [False] * 5
    assert "unknown tool" in observed[0].text
    assert "call look first" in observed[2].text
    assert "bad arguments" in observed[3].text
    assert "no steps" in observed[4].text
    assert record.status == "paused" and len(record.notes) == 6  # 5 refusals + the turn limit


# --- the checks on their own ------------------------------------------------------------------


def case_for(tmp_path, meta, narrated=True):
    job = make_job(tmp_path, narrated)
    transcript = artifacts.load(job, Transcript)
    case = Case(
        job,
        meta,
        rec.AgentRecord(objective="Build the side table"),
        10.0,
        [(t.start_s, t.end_s, t.text) for t in transcript.turns],
    )
    loop_frame = case.path("frames/t2.0.jpg")
    loop_frame.parent.mkdir(parents=True)
    cv2.imwrite(str(loop_frame), np.zeros((240, 320, 3), dtype=np.uint8))
    return case


def test_part_refused_when_sam_mask_barely_fills_the_box(tmp_path):
    case = case_for(tmp_path, FakeMeta([], sam_fill=0.01))
    result = add_part(case, "A", "bolt", 1, "frames/t2.0.jpg", [100, 400, 900, 900])
    assert not result.ok and "too loose" in result.text
    assert case.record.parts == []


def test_part_refused_for_bad_id_and_box(tmp_path):
    case = case_for(tmp_path, FakeMeta([]))
    assert (
        "capital letter" in add_part(case, "AB", "bolt", 1, "frames/t2.0.jpg", [1, 1, 50, 50]).text
    )
    assert "0..1000" in add_part(case, "A", "bolt", 1, "frames/t2.0.jpg", [5, 5, 6, 6]).text


def test_step_refusals(tmp_path):
    case = case_for(tmp_path, FakeMeta([]))
    add_part(case, "A", "bolt", 4, "frames/t2.0.jpg", [100, 400, 300, 600])
    base = dict(
        n=1,
        action="insert",
        text="Mete el tornillo.",
        parts=["A"],
        start_s=1.0,
        end_s=4.0,
        frame="frames/t2.0.jpg",
        to_box=[100, 400, 300, 600],
        quote="metemos el tornillo",
    )
    assert add_step(case, **base).ok
    assert "unknown" in add_step(case, **(base | {"parts": ["Z"]})).text
    assert "action must be" in add_step(case, **(base | {"action": "teleport"})).text
    assert "not in the narration" in add_step(case, **(base | {"quote": "nunca dijo esto"})).text
    assert "own words" in add_step(case, **(base | {"quote": ""})).text
    assert "start_s < end_s" in add_step(case, **(base | {"start_s": 5.0, "end_s": 2.0})).text
    assert "not inside the step" in add_step(case, **(base | {"start_s": 6.0, "end_s": 9.0})).text


def test_silent_video_needs_no_quote(tmp_path):
    case = case_for(tmp_path, FakeMeta([]), narrated=False)
    add_part(case, "A", "bolt", 1, "frames/t2.0.jpg", [100, 400, 300, 600])
    result = add_step(
        case,
        1,
        "insert",
        "Put the bolt in.",
        ["A"],
        1.0,
        3.0,
        "frames/t2.0.jpg",
        [100, 400, 300, 600],
        "",
    )
    assert result.ok


def test_submit_refuses_unused_parts_and_gaps(tmp_path):
    case = case_for(tmp_path, FakeMeta([]))
    add_part(case, "A", "bolt", 1, "frames/t2.0.jpg", [100, 400, 300, 600])
    add_part(case, "B", "leg", 1, "frames/t2.0.jpg", [100, 400, 300, 600])
    add_step(
        case,
        2,
        "insert",
        "Mete el tornillo.",
        ["A"],
        1.0,
        4.0,
        "frames/t2.0.jpg",
        [100, 400, 300, 600],
        "metemos el tornillo",
    )
    text = submit_guide(case).text
    assert "never used" in text and "1..N" in text


def test_helpers():
    assert valid_box([-5, 10, 1200, 500]) == (0, 10, 1000, 500)
    assert valid_box([1, 2, 3]) is None
    assert normalize("¡Ahora, METEMOS el tornillo!") == "ahora metemos el tornillo"


def test_fresh_start_never_discards_a_run_waiting_for_the_person(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    rec.save_record(job, rec.AgentRecord(status="needs_input"))
    started = []
    monkeypatch.setattr(loop.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert loop.launch(job) is False
    assert started == []
