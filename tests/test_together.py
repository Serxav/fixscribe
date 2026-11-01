"""Steps worked on at once keep their order, and fasteners keep one numbering."""

import threading

import pytest

from app.pipeline.perception import number_fasteners
from app.pipeline.together import in_parallel
from app.schemas import NormBox, ScrewRecord, StepPerception


def test_answers_keep_the_order_of_the_items():
    assert in_parallel([3, 1, 2], lambda n: n * 10, workers=3) == [30, 10, 20]


def test_items_really_run_at_the_same_time():
    both_in = threading.Barrier(2, timeout=5)  # breaks, and the test fails, if they run one by one
    assert in_parallel([1, 2], lambda n: both_in.wait() >= 0, workers=2) == [True, True]


def test_a_bad_worker_count_still_runs():
    assert in_parallel([1], lambda n: n, workers=0) == [1]


def test_an_error_that_gets_out_is_not_hidden():
    def fail(_):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        in_parallel([1], fail, workers=1)


def screw(number: int) -> ScrewRecord:
    box = NormBox(x=0.1, y=0.1, w=0.1, h=0.1)
    return ScrewRecord(id="S1", number=number, box=box, confidence=0.9)


def test_fasteners_are_numbered_across_steps_in_order():
    first = StepPerception(index=1, removed=[screw(1), screw(2)])
    empty = StepPerception(index=2)
    last = StepPerception(index=3, removed=[screw(1)])
    number_fasteners([first, empty, last])
    assert [r.id for r in first.removed + last.removed] == ["S1", "S2", "S3"]
    assert [r.number for r in first.removed + last.removed] == [1, 2, 1]
