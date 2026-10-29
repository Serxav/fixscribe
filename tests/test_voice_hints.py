"""When and where the fasteners are, from Spark watching the video with the narration."""

import numpy as np

from app import artifacts
from app.pipeline import fasteners, perception
from app.pipeline.plan import to_step
from app.schemas import DraftStep, ScrewMap, Step, Transcript, Turn


def _draft(**extra):
    return DraftStep(title="Insert pins", start_s=10, end_s=20, screw_count=4, **extra)


def test_the_plan_keeps_when_and_where():
    step = to_step(1, _draft(fastener_s=17.5, fastener_where=" four holes in the middle rail "))
    assert step.screws.seen_s == 17.5
    assert step.screws.where == "four holes in the middle rail"


def test_a_moment_outside_the_step_is_dropped():
    assert to_step(1, _draft(fastener_s=0)).screws.seen_s is None
    assert to_step(1, _draft(fastener_s=25)).screws.seen_s is None
    assert to_step(1, DraftStep(title="Look", start_s=1, end_s=2)).screws is None


def _frames(sharp_at):
    frames = {}
    for i in range(40, 60):
        frame = np.zeros((40, 40, 3), np.uint8)
        if i == sharp_at:
            frame[::2, ::2] = 255  # lots of edges: the sharpest frame
        frames[i] = frame
    return frames


def test_told_frame_is_the_sharpest_near_the_moment():
    step = Step(
        index=1,
        title="t",
        instruction="t",
        start_s=10,
        end_s=20,
        screws=ScrewMap(count=4, seen_s=15),
    )
    assert fasteners.told_frame(step, 10, _frames(52)) == 52  # 15 s = frame 50, ±5 frames


def test_told_frame_outside_the_loaded_frames_is_none():
    step = Step(
        index=1,
        title="t",
        instruction="t",
        start_s=10,
        end_s=20,
        screws=ScrewMap(count=4, seen_s=11),
    )
    assert fasteners.told_frame(step, 10, _frames(52)) is None
    no_moment = Step(
        index=1, title="t", instruction="t", start_s=10, end_s=20, screws=ScrewMap(count=4)
    )
    assert fasteners.told_frame(no_moment, 10, _frames(52)) is None


def test_said_during_takes_the_words_of_the_step(tmp_path):
    step = Step(index=1, title="t", instruction="t", start_s=10, end_s=20)
    assert perception.said_during(tmp_path, step) == ""
    turns = [
        Turn(start_s=0, end_s=5, text="Hola."),
        Turn(start_s=9.5, end_s=14, text="Ponemos los pernos en estos cuatro agujeros."),
        Turn(start_s=25, end_s=30, text="Ahora las patas."),
    ]
    artifacts.save(tmp_path, Transcript(mode="narrated", turns=turns))
    assert perception.said_during(tmp_path, step) == "Ponemos los pernos en estos cuatro agujeros."
