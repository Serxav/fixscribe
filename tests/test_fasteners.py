"""The fastener method: propose (sliced SAM), choose (Spark by number), follow, decide."""

import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.pipeline import fasteners
from app.pipeline.fasteners import Found
from app.schemas import Step


def _det(box, confidence=0.9):
    return SimpleNamespace(box=box, confidence=confidence)


class SliceSam:
    """Fake SAM that sees fasteners only where they are big enough: on the zoomed quarters.

    ``spots`` are boxes in full-image pixels; a spot is seen on a region when, enlarged, it is
    at least ``min_side`` pixels wide (a tiny screw needs the zoom, as with the real model).
    """

    def __init__(self, image_size, spots, min_side=0, words=("screw",)):
        self.width, self.height = image_size
        self.spots = spots
        self.min_side = min_side
        self.words = words
        self.calls = []

    def segment(self, path, concept, max_side=1280):
        self.calls.append((path.name, concept))
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        n = int(path.stem.removeprefix("region"))
        x1, y1, x2, y2 = fasteners.regions(self.width, self.height)[n]
        scale = w / (x2 - x1)
        found = []
        if concept not in self.words:
            return found, (w, h)
        for sx1, sy1, sx2, sy2 in self.spots:
            if not (x1 <= sx1 and sx2 <= x2 and y1 <= sy1 and sy2 <= y2):
                continue
            if (sx2 - sx1) * scale < self.min_side:
                continue
            found.append(
                _det(
                    ((sx1 - x1) * scale, (sy1 - y1) * scale, (sx2 - x1) * scale, (sy2 - y1) * scale)
                )
            )
        return found, (w, h)


def test_regions_cover_the_frame_with_overlapping_quarters():
    regions = fasteners.regions(1000, 500)
    assert regions[0] == (0, 0, 1000, 500)
    assert regions[1] == (0, 0, 600, 300) and regions[4] == (400, 200, 1000, 500)


def test_propose_maps_zoomed_finds_back_and_merges_duplicates(tmp_path):
    image = np.zeros((500, 1000, 3), dtype=np.uint8)
    sam = SliceSam((1000, 500), [(100, 100, 110, 110), (900, 400, 910, 410)])
    found = fasteners.propose(sam, image, "screw", tmp_path)
    boxes = sorted(tuple(round(v) for v in box) for _, box in found)
    assert boxes == [(100, 100, 110, 110), (900, 400, 910, 410)]  # each seen twice, kept once


def test_sliced_inference_finds_a_screw_too_small_for_the_whole_frame(tmp_path):
    image = np.zeros((500, 1000, 3), dtype=np.uint8)
    sam = SliceSam((1000, 500), [(100, 100, 108, 108)], min_side=12)
    assert len(fasteners.propose(sam, image, "screw", tmp_path)) == 1  # only on a quarter


def test_propose_drops_huge_and_weak_boxes_and_falls_back_to_the_last_word(tmp_path):
    image = np.zeros((500, 1000, 3), dtype=np.uint8)
    sam = SliceSam((1000, 500), [(100, 100, 110, 110), (0, 0, 400, 400)], words=("bolt",))
    found = fasteners.propose(sam, image, "allen bolt", tmp_path)
    assert [tuple(round(v) for v in box) for _, box in found] == [(100, 100, 110, 110)]
    assert {concept for _, concept in sam.calls} == {"allen bolt", "bolt"}


class Spark:
    def __init__(self, reject):
        self.reject = reject

    def respond(self, **kwargs):
        text = kwargs["input"][0]["content"][0]["text"]
        assert "green frame" in text  # numbered candidates, never coordinates
        tiles = [{"n": n, "real": n not in self.reject, "why": "t"} for n in range(1, 17)]
        return SimpleNamespace(output_text=json.dumps({"tiles": tiles}))


def test_choose_keeps_only_the_numbers_spark_confirms():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    candidates = [(0.9, (10, 10, 14, 14)), (0.8, (50, 50, 54, 54)), (0.7, (80, 10, 84, 14))]
    kept = fasteners.choose(Spark({2}), "muse-spark-1.3", image, candidates, "screw", "ctx")
    assert kept == [candidates[0], candidates[2]]


def test_choose_without_spark_keeps_everything():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    candidates = [(0.9, (10, 10, 14, 14))]
    assert (
        fasteners.choose(object(), "muse-spark-1.3", image, candidates, "screw", "") == candidates
    )


def _track(present):
    """frames 0..19; ``present`` maps id -> frames it is seen on."""
    return {i: {oid: (0, 0, 5, 5) for oid, seen in present.items() if i in seen} for i in range(20)}


def test_decide_building_keeps_what_appears_and_stays():
    frames = _track(
        {
            1: range(12, 20),  # put in during the step
            2: range(0, 20),  # was already there
            3: range(18, 20),  # seen on two frames only: not steady
        }
    )
    assert fasteners.decide(frames, [1, 2, 3], 20, adding=True) == [1]


def test_decide_keeps_a_clear_change_despite_a_few_early_false_sightings():
    frames = _track({1: list(range(0, 2)) + list(range(10, 20)), 2: range(0, 20)})
    assert fasteners.decide(frames, [1, 2], 20, adding=True) == [1]


def test_unique_drops_a_second_id_on_the_same_fastener():
    frames = {i: {1: (10, 10, 20, 20), 2: (11, 11, 19, 19), 3: (50, 50, 60, 60)} for i in range(5)}
    assert fasteners.unique(frames, [1, 2, 3]) == [1, 3]


def test_same_counts_a_box_inside_another():
    assert fasteners.same((0, 0, 20, 30), (2, 15, 18, 28))
    assert not fasteners.same((0, 0, 10, 10), (20, 20, 30, 30))


def test_decide_taking_apart_keeps_what_disappears():
    frames = _track({1: range(0, 8), 2: range(0, 20)})
    assert fasteners.decide(frames, [1, 2], 20, adding=False) == [1]


def test_follow_drops_boxes_that_grew_into_a_hand(tmp_path):
    class Video:
        def segment_video(self, clip, boxes=(), size=None):
            objects = [
                SimpleNamespace(object_id=1, box=(10, 10, 20, 20)),
                SimpleNamespace(object_id=2, box=(0, 0, 600, 400)),
            ]
            return [SimpleNamespace(frame=0, width=640, height=480, objects=objects)]

    seeds = [(0, (1, 1, 2, 2))] * 2
    frames = fasteners.follow(Video(), tmp_path / "c.mp4", (1280, 960), seeds)
    assert frames == {0: {1: (20.0, 20.0, 40.0, 40.0)}}  # scaled to the clip, 2 dropped


def test_found_round_trip_and_boxes_at_a_time():
    found = Found(fps=5, start_s=10.0, size=(640, 360), seed=2, kept=[1],
                  frames={2: {1: (1, 2, 3, 4), 2: (5, 6, 7, 8)}})  # fmt: skip
    back = Found.from_json(json.loads(json.dumps(found.to_json())))
    assert back == found
    assert back.boxes_at(10.4) == {1: (1, 2, 3, 4)}  # frame 2; id 2 was not kept
    assert back.boxes_at(9.0) == {} and back.boxes_at(20.0) == {}


def test_clip_fps_fits_a_step_in_the_frame_budget():
    assert fasteners.clip_fps(5) == fasteners.MAX_FPS
    assert fasteners.clip_fps(60) == pytest.approx(2.0)
    assert fasteners.clip_fps(600) == fasteners.MIN_FPS


def test_step_fastener_prefers_the_step_s_own_word():
    step = Step(index=1, title="t", instruction="i", start_s=0, end_s=1,
                removes=["side rail", "Allen bolts"])  # fmt: skip
    assert fasteners.step_fastener(step, "screw") == "allen bolts"
    plain = Step(index=1, title="t", instruction="i", start_s=0, end_s=1, removes=["cover"])
    assert fasteners.step_fastener(plain, "screw") == "screw"


def test_twin_tracks_are_merged_into_one_box():
    frames = {0: {1: (10, 20, 30, 40), 2: (8, 10, 32, 38)}}
    assert fasteners.unique(frames, [1, 2]) == [1]
    assert frames == {0: {1: (8, 10, 32, 40)}}


def test_step_fasteners_lists_every_kind_the_step_names():
    step = Step(index=1, title="t", instruction="i", start_s=0, end_s=1,
                removes=["metal washer", "hex nut", "rail", "spring washer"])  # fmt: skip
    assert fasteners.step_fasteners(step, "screw") == ["metal washer", "hex nut"]
