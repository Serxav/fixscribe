"""Perception stage with fake SAM/Spark and a small generated video (no network)."""

import json
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaError
from app.pipeline import fasteners, locate, perception
from app.pipeline.perception import part_concept, part_concepts
from app.schemas import Frames, Plan, ScrewMap, Step, StepMedia

W, H = 320, 240
SPOTS = [(60, 60, 70, 70), (200, 60, 210, 70), (60, 160, 70, 170)]  # fasteners, video pixels


@pytest.fixture(autouse=True)
def whole_frame(monkeypatch):
    """Track on the whole clip: the fake SAM video below knows fasteners by their place."""
    monkeypatch.setattr(fasteners, "MIN_AREA", 1.0)


def _det(box, confidence=0.9):
    return SimpleNamespace(box=box, confidence=confidence)


class FakeMeta:
    """SAM finds the part on stills and the ``SPOTS`` on the whole-frame region; SAM video says
    which fasteners are seen on each frame (``present(spot, frame, count)``, spot 1..3 is the
    fastener at that place, whatever id it was given)."""

    def __init__(self, present=None, fail_on_call=None, meta_fail_on_call=None):
        self.present = present or (lambda oid, frame, count: frame >= count // 2)  # put in
        self.fail_on_call = fail_on_call
        self.meta_fail_on_call = meta_fail_on_call
        self.calls = []

    def _count(self, kind):
        self.calls.append(kind)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise BudgetExceeded("budget reached")
        if self.meta_fail_on_call is not None and len(self.calls) == self.meta_fail_on_call:
            raise MetaError("sam failed")

    def segment(self, path, concept, max_side=1280):
        self._count("find")
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        if not path.name.startswith("region"):  # the part, on the keyframe still
            return [_det((w * 0.1, h * 0.1, w * 0.9, h * 0.9))], (w, h)
        if path.name != "region0.png":
            return [], (w, h)
        sx, sy = w / W, h / H
        return [_det((a * sx, b * sy, c * sx, d * sy)) for a, b, c, d in SPOTS], (w, h)

    def ground(self, path, query, *, context="", max_boxes=8):
        return [SimpleNamespace(label=query, box=(100, 100, 900, 900), why="t")]

    def segment_boxes(self, path, boxes, max_side=1280):
        self._count("find")
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        size = (w // 2, h // 2)
        detection = SimpleNamespace(
            box=(0, 0, size[0], size[1]),
            confidence=0.9,
            mask=bytes([1]) * (size[0] * size[1]),
            mask_size=size,
            mask_bounds=(0, 0, size[0], size[1]),
        )
        return [detection], (w, h)

    def respond(self, **kwargs):
        if kwargs["text"]["format"]["name"] == "pick_frames":
            return SimpleNamespace(output_text=json.dumps({"frames": [1]}))
        content = kwargs["input"][0]["content"]
        tiles = [{"n": n, "real": True, "why": "t"} for n in range(1, len(content))]
        return SimpleNamespace(output_text=json.dumps({"tiles": tiles}))

    def segment_video(self, clip, boxes=(), size=None):
        self._count("follow")
        count = fasteners.frame_count(clip)
        return [
            SimpleNamespace(
                frame=i,
                width=size[0],
                height=size[1],
                objects=[
                    SimpleNamespace(object_id=oid, box=box)
                    for oid, _, box in boxes
                    if self.present(_spot(box), i, count)
                ],
            )
            for i in range(count)
        ]


def _spot(box):
    """1-based index of the SPOTS fastener nearest to ``box`` (clip pixels = video pixels)."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    centres = [((a + c) / 2, (b + d) / 2) for a, b, c, d in SPOTS]
    return 1 + min(
        range(len(SPOTS)), key=lambda n: (centres[n][0] - cx) ** 2 + (centres[n][1] - cy) ** 2
    )


def _step(index, start, end, screws=0, target="rail", removes=None):
    return Step(
        index=index,
        title=f"Step {index}",
        instruction=f"Do step {index}.",
        start_s=start,
        end_s=end,
        target_part=target,
        removes=removes or [],
        screws=ScrewMap(count=screws) if screws else None,
    )


def _job(tmp_path, steps, task=None):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={W}x{H}:rate=30",
         "-t", "8", "-pix_fmt", "yuv420p", str(tmp_path / "video.mp4")],
        check=True,
    )  # fmt: skip
    media = []
    for step in steps:
        still = tmp_path / "stills" / f"{step.index:02d}.png"
        still.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(still), np.full((H, W, 3), 120, dtype=np.uint8))
        media.append(
            StepMedia(
                index=step.index,
                keyframe_s=(step.start_s + step.end_s) / 2,
                image=f"steps/{step.index:02d}.jpg",
                still=f"stills/{step.index:02d}.png",
            )
        )
    artifacts.save(tmp_path, Plan(title="G", device="Table", mode="silent", duration_s=8.0,
                                  steps=steps))  # fmt: skip
    artifacts.save(tmp_path, Frames(steps=media))
    if task:
        data = {"object_name": "garden table", "category": "furniture", "task": task}
        (tmp_path / "identity.json").write_text(json.dumps(data), encoding="utf-8")
    return Settings(model_api_key="", data_dir=tmp_path)


def test_building_step_keeps_the_fasteners_that_appear(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=3)], task="assemble")
    result = perception.run(tmp_path, settings, client=FakeMeta())
    step = result.steps[0]
    assert [record.id for record in step.removed] == ["S1", "S2", "S3"]
    centres = [c for r in step.removed for c in (r.box.x + r.box.w / 2, r.box.y + r.box.h / 2)]
    assert centres == pytest.approx([65 / W, 65 / H, 205 / W, 65 / H, 65 / W, 165 / H])
    assert step.notes == []
    assert (tmp_path / step.overlay).is_file()
    found = fasteners.load_found(tmp_path, 1)
    assert found is not None and found.kept == [1, 2, 3]
    assert not (tmp_path / "steps" / "01_work").exists()  # the working clip is removed


def test_fasteners_already_there_are_not_counted(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=3)], task="assemble")
    client = FakeMeta(present=lambda oid, f, c: oid == 2 or f >= c // 2)  # 2 was already in
    step = perception.run(tmp_path, settings, client=client).steps[0]
    assert len(step.removed) == 2
    assert "2 of 3 screws put in are clearly visible" in step.notes[0]


def test_taking_apart_keeps_the_fasteners_that_disappear(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=1)], task="repair")
    client = FakeMeta(present=lambda oid, f, c: oid != 1 or f < c // 2)
    step = perception.run(tmp_path, settings, client=client).steps[0]
    assert len(step.removed) == 1


class CheckingMeta(FakeMeta):
    def respond(self, **kwargs):
        if kwargs["text"]["format"]["name"] == "pick_frames":
            return SimpleNamespace(output_text=json.dumps({"frames": [1]}))
        content = kwargs["input"][0]["content"]
        tiles = [{"n": n, "real": n != 2, "why": "t"} for n in range(1, len(content))]
        return SimpleNamespace(output_text=json.dumps({"tiles": tiles}))


def test_spark_drops_a_followed_candidate_that_is_not_a_fastener(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=3)], task="assemble")
    step = perception.run(tmp_path, settings, client=CheckingMeta()).steps[0]
    assert len(step.removed) == 2


def test_never_more_fasteners_than_the_analysis_counted(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=2)], task="assemble")
    step = perception.run(tmp_path, settings, client=FakeMeta()).steps[0]
    assert len(step.removed) == 2


def test_nothing_visible_means_nothing_invented(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=4)], task="assemble")
    client = FakeMeta(present=lambda oid, f, c: f % 3 == 0)  # flickering: never steady
    step = perception.run(tmp_path, settings, client=client).steps[0]
    assert step.removed == []
    assert "0 of 4 screws put in are clearly visible" in step.notes[0]


def test_step_without_fasteners_only_finds_the_part(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0)])
    client = FakeMeta()
    step = perception.run(tmp_path, settings, client=client).steps[0]
    assert step.part is not None and step.part.concept == "rail"
    assert client.calls == ["find"]
    assert step.sam_calls == 1


def test_budget_stops_cleanly_and_keeps_earlier_steps(tmp_path):
    steps = [_step(1, 0.0, 3.0, screws=3), _step(2, 4.0, 7.0, screws=3)]
    settings = _job(tmp_path, steps, task="assemble")
    # step 1: part + 5 regions + follow = 7 calls; step 2 stops on its first fastener call
    result = perception.run(tmp_path, settings, client=FakeMeta(fail_on_call=9))
    assert len(result.steps[0].removed) == 3
    assert result.steps[1].part is not None
    assert "SAM budget reached." in result.steps[1].notes
    assert result.sam_calls == 9


def test_a_failing_step_keeps_the_others(tmp_path):
    steps = [_step(1, 0.0, 3.0, screws=3), _step(2, 4.0, 7.0, screws=3)]
    settings = _job(tmp_path, steps, task="assemble")
    result = perception.run(tmp_path, settings, client=FakeMeta(meta_fail_on_call=1))
    # the part failed, the fasteners of the same step still count
    assert result.steps[0].part is None and len(result.steps[0].removed) == 3
    assert len(result.steps[1].removed) == 3


def test_max_steps(tmp_path):
    steps = [_step(i, 0.0, 1.0) for i in range(1, 25)]
    settings = _job(tmp_path, steps)
    result = perception.run(tmp_path, settings, client=FakeMeta())
    assert [step.index for step in result.steps] == list(range(1, perception.MAX_STEPS + 1))


def test_job_fastener_word_comes_from_the_domain(tmp_path):
    _job(tmp_path, [_step(1, 0.0, 1.0)])
    assert fasteners.fastener_concept(tmp_path) == "screw"
    data = {"object_name": "sedan", "category": "automotive", "task": "repair"}
    (tmp_path / "identity.json").write_text(json.dumps(data), encoding="utf-8")
    assert fasteners.fastener_concept(tmp_path) == "bolt"


@pytest.mark.parametrize(
    ("target", "removes", "expected"),
    [
        ("the battery connector bracket", [], "connector bracket"),
        ("", [], None),
        (None, [], None),
        ("Back cover", [], "back cover"),
        (None, ["the back cover"], "back cover"),
        ("battery", [], "battery"),
    ],
)
def test_part_concept(target, removes, expected):
    assert part_concept(target, removes) == expected


def test_part_concepts_prefer_plain_words_then_the_head_noun():
    step = Step(index=1, title="t", instruction="i", start_s=0, end_s=1, sam_concept="wooden leg",
                target_part="leg frame C", removes=["Rail C"])  # fmt: skip
    assert part_concepts(step) == ["wooden leg", "leg", "frame c"]


def test_part_concepts_ask_for_the_part_before_a_tool_next_to_it():
    step = Step(index=1, title="t", instruction="i", start_s=0, end_s=1, target_part="back cover",
                sam_concept="yellow bottle")  # fmt: skip
    assert part_concepts(step)[0] == "back cover"


def _locate_job(tmp_path):
    return _job(tmp_path, [_step(1, 0.0, 4.0)])


def test_a_weak_cut_out_is_not_shown_and_the_reason_is_saved(tmp_path):
    settings = _locate_job(tmp_path)

    class Weak(FakeMeta):
        def segment_boxes(self, path, boxes, max_side=1280):
            detections, size = super().segment_boxes(path, boxes, max_side)
            detections[0].confidence = 0.46  # a real wrong cut-out scored this
            return detections, size

    step = perception.run(tmp_path, settings, client=Weak()).steps[0]
    assert step.part is None
    record = json.loads((tmp_path / "steps" / "01_part.json").read_text())
    assert record["tries"][0]["result"] == "weak cut-out"


def test_a_cut_out_spark_rejects_is_not_shown(tmp_path):
    settings = _locate_job(tmp_path)

    class Rejects(FakeMeta):
        def respond(self, **kwargs):
            if kwargs["text"]["format"]["name"] == "pick_frames":
                return super().respond(**kwargs)
            tiles = [{"n": 1, "real": False, "why": "that is the mat"}]
            return SimpleNamespace(output_text=json.dumps({"tiles": tiles}))

    step = perception.run(tmp_path, settings, client=Rejects()).steps[0]
    assert step.part is None and "could not be proven" in step.notes[0]


def test_a_part_spark_cannot_see_costs_no_sam_call(tmp_path):
    settings = _locate_job(tmp_path)

    class Hidden(FakeMeta):
        def respond(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps({"frames": []}))

    client = Hidden()
    step = perception.run(tmp_path, settings, client=client).steps[0]
    assert step.part is None and client.calls == []


def test_the_part_keeps_the_second_it_was_found(tmp_path):
    settings = _locate_job(tmp_path)
    step = perception.run(tmp_path, settings, client=FakeMeta()).steps[0]
    assert step.part.t_s is not None and 0 <= step.part.t_s <= 4


def test_the_part_is_found_on_a_zoom_and_its_box_comes_back_to_the_whole_frame():
    assert locate.to_full((0, 0, 1000, 1000), (200, 300, 600, 700)) == (200, 300, 600, 700)
    assert locate.to_full((500, 500, 750, 750), (200, 300, 600, 700)) == (400, 500, 500, 600)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    assert locate.zoomed(frame, (250, 250, 750, 750)).shape[:2] == (720, 1280)
    assert locate.zoomed(frame, None) is frame


def test_a_bad_answer_from_spark_does_not_lose_the_step(tmp_path):
    settings = _locate_job(tmp_path)

    class Garbled(FakeMeta):
        def respond(self, **kwargs):
            return SimpleNamespace(output_text="not json")

    step = perception.run(tmp_path, settings, client=Garbled()).steps[0]
    assert step.part is None and "could not be proven" in step.notes[0]


def test_small_fasteners_are_found_going_through_the_step_slowly(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 4.0, screws=2)], task="assemble")

    class Slow(FakeMeta):
        def __init__(self):
            super().__init__(present=lambda oid, f, c: False)  # the search finds nothing
            self.slow = []

        def respond(self, **kwargs):
            if kwargs["text"]["format"]["name"] == "slow_look":
                self.slow.append(len(kwargs["input"][0]["content"]) - 1)
                answer = {"frame": 3, "points": [{"x": 300, "y": 300}, {"x": 700, "y": 700}]}
                return SimpleNamespace(output_text=json.dumps(answer))
            return super().respond(**kwargs)

    client = Slow()
    step = perception.run(tmp_path, settings, client=client).steps[0]
    assert client.slow == [locate.SLOW_FRAMES]
    assert [record.number for record in step.removed] == [1, 2]
