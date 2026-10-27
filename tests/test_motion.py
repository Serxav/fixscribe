"""Motion stage: SAM video tracks -> cinematic clip, part cut-out and outline (no network)."""

import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app import artifacts
from app.config import Settings
from app.pipeline import motion
from app.schemas import Motion, Plan, ScrewMap, Step


def _obj(object_id, box, mask=None):
    return SimpleNamespace(object_id=object_id, box=box, confidence=0.9, mask=mask, svg_path=None)


def _frame(index, objects, size=(40, 30)):
    return SimpleNamespace(frame=index, width=size[0], height=size[1], objects=objects)


def test_clip_window_keeps_short_steps_and_centers_long_ones():
    assert motion.clip_window(2.0, 6.0) == (2.0, 6.0)
    assert motion.clip_window(0.0, 20.0) == (6.0, 14.0)


def test_to_track_unions_masks_and_scales_boxes():
    mask = np.zeros((30, 40), dtype=bool)
    mask[5:10, 5:10] = True
    track = motion.to_track([_frame(3, [_obj(1, (0, 0, 20, 15), mask)])], (80, 60))
    assert track.masks[3].shape == (60, 80) and track.masks[3].any()
    assert track.objects[3][1] == (0, 0, 40, 30)  # scaled 2x to the clip size


def test_held_mask_fades_over_skipped_frames():
    mask = np.ones((4, 4), dtype=bool)
    track = motion.Track(masks={10: mask}, objects={})
    assert motion.held_mask(track, 10, (4, 4))[1] == 1.0
    assert 0 < motion.held_mask(track, 12, (4, 4))[1] < 1.0
    assert motion.held_mask(track, 10 + motion.HOLD_FRAMES + 1, (4, 4))[1] == 0.0


def test_only_fasteners_that_disappear_are_numbered():
    boxes = {1: (10, 10, 14, 14), 2: (30, 10, 34, 14), 3: (10, 40, 14, 44)}
    objects = {i: dict(boxes) for i in range(20)}
    for i in range(8, 20):
        objects[i].pop(2)  # fastener 2 comes out at frame 8
    track = motion.Track(masks={}, objects=objects)
    removed = motion.removed_fasteners(track, 20)
    assert removed == {2: 7}
    assert motion.fastener_numbers(track, set(removed)) == {2: 1}
    assert motion.fastener_numbers(track) == {1: 1, 2: 2, 3: 3}  # reading order


def test_render_frame_dims_the_scene_and_keeps_the_part():
    frame = np.full((60, 80, 3), 200, dtype=np.uint8)
    part = np.zeros((60, 80), dtype=bool)
    part[20:40, 30:50] = True
    out = motion.render_frame(frame, part, 1.0, {7: (5, 5, 9, 9)}, {7: 1}, t=0.5)
    assert out.shape == frame.shape
    assert out[5, 70].mean() < 120  # background dimmed
    assert out[30, 40].mean() > 180  # the part stays bright


def test_outline_and_cutout(tmp_path):
    frame = np.full((100, 200, 3), 90, dtype=np.uint8)
    mask = np.zeros((100, 200), dtype=bool)
    mask[20:60, 50:150] = True
    path = motion.outline_path(mask)
    assert path.startswith("M") and path.endswith("Z")
    box = motion.cutout(frame, mask, tmp_path / "steps" / "01_cutout.png")
    assert (round(box.x, 2), round(box.y, 2), round(box.w, 2), round(box.h, 2)) == (
        0.25,
        0.2,
        0.5,
        0.4,
    )
    image = cv2.imread(str(tmp_path / "steps" / "01_cutout.png"), cv2.IMREAD_UNCHANGED)
    assert image.shape[2] == 4 and image[20, 50, 3] > 200


class FakeSam:
    """Tracks a bright square (the part) and two small dots (one of them is removed)."""

    def __init__(self):
        self.concepts = []

    def segment_video(self, path, concept, max_frames=600):
        self.concepts.append(concept)
        capture = cv2.VideoCapture(str(path))
        frames, index = [], 0
        while True:
            ok, image = capture.read()
            if not ok:
                break
            h, w = image.shape[:2]
            if concept == "screw":
                objects = [_obj(1, (10, 10, 18, 18))]
                if index < 10:
                    objects.append(_obj(2, (40, 10, 48, 18)))
            else:
                mask = np.zeros((h, w), dtype=bool)
                mask[h // 4 : h // 2, w // 4 : w // 2] = True
                objects = [_obj(1, (w // 4, h // 4, w // 2, h // 2), mask)]
            frames.append(_frame(index, objects, (w, h)))
            index += 1
        capture.release()
        return frames


@pytest.fixture
def job(tmp_path):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
         "-t", "3", "-pix_fmt", "yuv420p", str(tmp_path / "video.mp4")],
        check=True,
    )  # fmt: skip
    steps = [
        Step(index=1, title="Open", instruction="Lift the cover.", start_s=0.2, end_s=2.5,
             target_part="back cover", screws=ScrewMap(count=1)),
        Step(index=2, title="Look", instruction="Look.", start_s=2.5, end_s=2.9),
    ]  # fmt: skip
    artifacts.save(tmp_path, Plan(title="t", device="d", mode="silent", duration_s=3, steps=steps))
    return tmp_path


def test_run_renders_clips_cutout_and_counts_the_removed_fastener(job):
    sam = FakeSam()
    result = motion.run(job, Settings(), client=sam)
    assert sam.concepts == ["back cover", "screw"]  # step 2 has no part: skipped
    step = result.steps[0]
    assert step.fasteners_tracked == 1  # only the one that came out
    for path in (step.clip, step.clip_reverse, step.cutout):
        assert (job / path).is_file()
    assert step.outline.startswith("M") and step.cutout_box is not None
    assert not (job / "steps" / "01_src.mp4").exists()  # the working clip is removed
    assert artifacts.load(job, Motion) == result


def test_one_failing_step_does_not_stop_the_others(job):
    class Broken(FakeSam):
        def segment_video(self, path, concept, max_frames=600):
            raise RuntimeError("SAM down")

    result = motion.run(job, Settings(), client=Broken())
    assert result.steps == []
    assert result.notes == ["Step 1: no motion clip (SAM down)."]


def test_box_local_masks_are_placed_inside_their_box():
    local = np.ones((5, 10), dtype=bool)  # what SAM sends: the mask of the box only
    track = motion.to_track([_frame(0, [_obj(1, (20, 10, 30, 15), local)], (40, 30))], (40, 30))
    ys, xs = np.nonzero(track.masks[0])
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (20, 29, 10, 14)
