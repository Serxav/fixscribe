"""Strange model answers on the live coach: it may say it cannot answer, it may never crash.

A judge points a camera at anything. Whatever Spark or SAM sends back, the coach either gives a
valid answer or raises LiveError with a sentence the page can show.
"""

import json
import types

import pytest

from app import artifacts
from app.config import Settings
from app.meta_client import MetaError
from app.pipeline.ask import answer_question
from app.pipeline.live import LiveAnswer, LiveError, live_marks, live_turn
from tests.test_live import FakeLiveClient, FakeMarksClient, _frame_bytes, _guide, _with_target


class Says:
    """Spark answers with exactly this text."""

    def __init__(self, text):
        self.text = text

    def respond(self, **kwargs):
        return types.SimpleNamespace(output_text=self.text)


TURNS = {
    "broken json": "{\"step\": 1, \"sta",
    "empty": "",
    "a list": "[1, 2, 3]",
    "a number": "7",
    "null": "null",
    "step far past the end": json.dumps({"step": 999, "status": "on_track", "say": "x",
                                         "next": "y", "confidence": 0.9}),
    "negative step": json.dumps({"step": -3, "status": "wrong", "say": "x", "next": "y",
                                 "confidence": -1}),
    "step as text": json.dumps({"step": "two", "status": "on_track", "say": "", "next": "",
                                "confidence": 0.5}),
    "unknown status": json.dumps({"step": 1, "status": "dancing", "say": "x", "next": "y",
                                  "confidence": 0.5}),
    "nothing but a step": json.dumps({"step": 1}),
    "huge words": json.dumps({"step": 1, "status": "on_track", "say": "word " * 5000,
                              "next": "go " * 5000, "confidence": 0.5}),
    "box off the frame": json.dumps({"step": 1, "status": "on_track", "say": "x", "next": "y",
                                     "confidence": 0.5, "object_box": {"visible": True,
                                     "x_min": -400, "y_min": 900, "x_max": 5000, "y_max": 10}}),
    "confidence as text": json.dumps({"step": 1, "status": "on_track", "say": "x", "next": "y",
                                      "confidence": "high"}),
}  # fmt: skip


@pytest.mark.parametrize("case", list(TURNS))
def test_a_strange_turn_answer_never_crashes(tmp_path, case):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide(steps=3))
    try:
        answer = live_turn(
            tmp_path, settings, _frame_bytes(), last_step=1, client=Says(TURNS[case])
        )
    except LiveError as exc:
        assert str(exc) and len(str(exc)) < 400
        return
    assert isinstance(answer, LiveAnswer)
    assert 0 <= answer.step <= 3 and 0 <= answer.confidence <= 1
    assert all(0 <= v <= 1000 for v in answer.object_box)


def test_a_frame_that_is_not_a_picture_is_refused(tmp_path):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    artifacts.save(tmp_path, _guide())
    for frame in (b"", b"not a jpeg at all", b"\xff\xd8\xff" + b"\x00" * 50):
        with pytest.raises(LiveError):
            live_turn(tmp_path, settings, frame, client=FakeLiveClient({"step": 1}))


class OddMarks(FakeMarksClient):
    """Spark points at impossible boxes and SAM cuts out odd shapes."""

    def __init__(self, boxes, cuts, verdict):
        super().__init__()
        self.answer = verdict
        self.boxes, self.cuts = boxes, cuts

    def ground(self, path, query, *, context="", max_boxes=8, effort="medium"):
        return [types.SimpleNamespace(label=label, box=box) for label, box in self.boxes]

    def segment_boxes(self, path, boxes):
        return self.cuts, (320, 240)


def _cut(box, mask=None, size=(100, 100)):
    return types.SimpleNamespace(object_id="1", confidence=0.9, mask=mask, mask_size=size,
                                 mask_bounds=box, box=box)  # fmt: skip


FULL = bytes([1] * 100 * 100)
MARKS = {
    "inverted box": ([("back cover", (500, 500, 100, 100))], [_cut((32, 24, 160, 120), FULL)], {}),
    "box off the grid": ([("back cover", (-300, -300, 4000, 4000))], [_cut((0, 0, 320, 240), FULL)],
                         {}),
    "zero area box": ([("back cover", (200, 200, 200, 200))], [_cut((10, 10, 10, 10), FULL)], {}),
    "SAM cuts nothing": ([("back cover", (100, 100, 500, 500))], [], {}),
    "SAM sends no mask": ([("back cover", (100, 100, 500, 500))], [_cut((32, 24, 160, 120))], {}),
    "SAM mask of the wrong size": ([("back cover", (100, 100, 500, 500))],
                                   [_cut((32, 24, 160, 120), bytes([1] * 7))], {}),
    "a name not in the manual": ([("unicorn horn", (100, 100, 500, 500))],
                                 [_cut((32, 24, 160, 120), FULL)], {}),
    "more cuts than boxes": ([("back cover", (100, 100, 500, 500))],
                             [_cut((32, 24, 160, 120), FULL)] * 9, {}),
    "check says gibberish": ([("back cover", (100, 100, 500, 500))],
                             [_cut((32, 24, 160, 120), FULL)], {"tiles": "yes"}),
    "check names tile 99": ([("back cover", (100, 100, 500, 500))],
                            [_cut((32, 24, 160, 120), FULL)],
                            {"tiles": [{"n": 99, "real": True, "why": ""}]}),
}  # fmt: skip


@pytest.mark.parametrize("case", list(MARKS))
def test_strange_marks_never_crash(tmp_path, case):
    settings = _with_target(tmp_path)
    boxes, cuts, verdict = MARKS[case]
    try:
        parts = live_marks(
            tmp_path, settings, _frame_bytes(), 1, [], OddMarks(boxes, cuts, verdict)
        )
    except LiveError as exc:
        assert str(exc)
        return
    for part in parts:
        assert all(0 <= v <= 1000 for v in part.box)
        assert all(0 <= x <= 1000 and 0 <= y <= 1000 for x, y in part.outline)
    if case == "a name not in the manual":
        assert not parts  # a wrong name is never shown


def test_marks_survive_the_api_failing(tmp_path):
    settings = _with_target(tmp_path)
    parts = live_marks(tmp_path, settings, _frame_bytes(), 1, [], FakeMarksClient(MetaError("500")))
    assert parts == []


QUESTIONS = {
    "broken json": "{\"answer\": \"Tur",
    "no answer": json.dumps({"answer": "", "step": 1}),
    "answer is a list": json.dumps({"answer": ["a"], "step": 1}),
    "step past the end": json.dumps({"answer": "Use the T5 driver.", "step": 99}),
    "step as text": json.dumps({"answer": "Use the T5 driver.", "step": "2"}),
    "step as true": json.dumps({"answer": "Use the T5 driver.", "step": True}),
}  # fmt: skip


@pytest.mark.parametrize("case", list(QUESTIONS))
def test_a_strange_question_answer_never_crashes(tmp_path, case):
    settings = Settings(model_api_key="", data_dir=tmp_path)
    guide = _guide(steps=3)
    try:
        answer = answer_question(
            tmp_path, settings, guide, 1, "Which driver?", b"", Says(QUESTIONS[case])
        )
    except LiveError as exc:
        assert str(exc).startswith("could not answer the question")
        return
    assert answer.text and answer.step in (0, 1, 2, 3)
    assert type(answer.step) is int
