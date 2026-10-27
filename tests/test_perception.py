"""Perception tests with a fake SAM client and synthetic stills."""

import json

import cv2
import numpy as np
import pytest

from app import artifacts
from app.config import Settings
from app.meta_client import BudgetExceeded, Detection, MetaError
from app.pipeline import perception
from app.pipeline.perception import part_concept
from app.schemas import Frames, Plan, ScrewMap, Step, StepMedia

SIZE = 200


def _det(box, confidence=0.9):
    return Detection(
        object_id="x",
        box=tuple(float(v) for v in box),
        confidence=confidence,
        mask=None,
        mask_size=None,
        mask_bounds=None,
    )


def _norm_to_px(box, size):
    x, y, w, h = box
    return (x * size, y * size, (x + w) * size, (y + h) * size)


class FakeClient:
    """Returns detections from normalized full-still boxes, by file name.

    ``part`` maps a concept to one normalized box. ``before``/``after`` map a
    two-digit step prefix to normalized screw boxes on that still. The fake
    converts them to pixels of the image it actually receives, exactly as a
    real SAM answer would be scaled to the crop it was sent.
    """

    def __init__(
        self, part=None, before=None, after=None, fail_on_call=None, meta_fail_on_call=None
    ):
        self.part = part or {}
        self.before = before or {}
        self.after = after or {}
        self.fail_on_call = fail_on_call
        self.meta_fail_on_call = meta_fail_on_call
        self.calls = []

    def segment(self, image_path, concept, max_side=1280):
        image = cv2.imread(str(image_path))
        assert image is not None
        height, width = image.shape[:2]
        self.calls.append((image_path.name, concept, (width, height)))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise BudgetExceeded("budget reached")
        if self.meta_fail_on_call is not None and len(self.calls) == self.meta_fail_on_call:
            raise MetaError("sam failed")
        name = image_path.name
        if concept in ("screw", "bolt"):
            prefix = name[:2]
            source = self.before if "_before" in name else self.after
            boxes = source.get(prefix, [])
            # Crops here cover the whole still in most tests, so normalized
            # boxes scale straight onto the crop. The crop-mapping test
            # overrides this fake's behaviour through ``crop_boxes``.
            crop_boxes = getattr(self, "crop_boxes", None)
            if crop_boxes is not None:
                return crop_boxes(name, (width, height)), (width, height)
            return [_det(_norm_to_px(box, width)) for box in boxes], (width, height)
        box = self.part.get(concept)
        return ([_det(_norm_to_px(box, width))] if box else []), (width, height)


def _still(path, screws=()):
    image = np.full((SIZE, SIZE, 3), 120, dtype=np.uint8)
    cv2.rectangle(image, (40, 40), (160, 160), (40, 40, 40), -1)
    for cx, cy in screws:
        cv2.circle(image, (cx, cy), 3, (230, 230, 230), -1)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)


def _step(index, start, end, screws=0, target="battery"):
    return Step(
        index=index,
        title=f"Step {index}",
        instruction=f"Do step {index}.",
        start_s=start,
        end_s=end,
        target_part=target,
        screws=ScrewMap(count=screws) if screws else None,
    )


def _job(tmp_path, steps, still_steps=None):
    still_steps = still_steps if still_steps is not None else steps
    media = []
    for step in still_steps:
        name = f"{step.index:02d}.png"
        _still(tmp_path / "stills" / name)
        _still(tmp_path / "stills" / f"{step.index:02d}_before.png")
        _still(tmp_path / "stills" / f"{step.index:02d}_after.png")
        media.append(
            StepMedia(
                index=step.index,
                keyframe_s=(step.start_s + step.end_s) / 2,
                image=f"steps/{step.index:02d}.jpg",
                still=f"stills/{name}",
            )
        )
    plan = Plan(title="Guide", device="Phone", mode="silent", duration_s=60.0, steps=steps)
    artifacts.save(tmp_path, plan)
    artifacts.save(tmp_path, Frames(steps=media))
    return Settings(model_api_key="", data_dir=tmp_path)


# Four screws: two on the top row, two on the bottom row (normalized boxes).
FOUR = [
    (0.20, 0.20, 0.05, 0.05),
    (0.60, 0.20, 0.05, 0.05),
    (0.20, 0.60, 0.05, 0.05),
    (0.60, 0.60, 0.05, 0.05),
]
PART = {"battery": (0.10, 0.10, 0.80, 0.80)}


def test_removed_screws_numbered_in_reading_order_across_steps(tmp_path):
    steps = [_step(1, 0.0, 5.0, screws=4), _step(2, 5.0, 10.0, screws=1)]
    settings = _job(tmp_path, steps)
    client = FakeClient(
        part=PART,
        before={"01": FOUR, "02": [(0.30, 0.30, 0.05, 0.05)]},
        after={"01": [FOUR[1]], "02": []},
    )
    result = perception.run(tmp_path, settings, client=client)

    first, second = result.steps
    assert [record.id for record in first.removed] == ["S1", "S2", "S3"]
    assert [record.number for record in first.removed] == [1, 2, 3]
    # Reading order: top-left, bottom-left, bottom-right (top-right stayed).
    centres = [(r.box.x + r.box.w / 2, r.box.y + r.box.h / 2) for r in first.removed]
    assert centres == [(0.225, 0.225), (0.225, 0.625), (0.625, 0.625)]
    assert first.screws_before == 4
    assert first.screws_after == 1
    assert [record.id for record in second.removed] == ["S4"]
    assert first.part is not None and first.part.concept == "battery"
    assert first.overlay == "steps/01_overlay.jpg"
    assert (tmp_path / first.overlay).is_file()
    # 2 part calls + 2 screw calls per screw step.
    assert result.sam_calls == 6
    assert artifacts.load(tmp_path, perception.Perception) == result


def test_crop_mapping_returns_screw_to_full_still_position(tmp_path):
    step = _step(1, 0.0, 5.0, screws=1, target="the battery connector bracket")
    settings = _job(tmp_path, [step])
    client = FakeClient(part={"connector bracket": (0.25, 0.25, 0.20, 0.20)})

    def crop_boxes(name, size):
        if "_before" not in name:
            return []
        # Part pixels 100..180 on the 200 px still in this test's scale are
        # replaced below by a 400 px still; see ``_job`` note. The crop the
        # stage builds grows that box by 1.6, so a screw whose full-still
        # box starts at pixel 136 sits at (136 - 76) * upscale in the crop.
        width, _ = size
        factor = width / 128  # crop is 128 px wide before the upscale
        return [
            _det(
                ((136 - 76) * factor, (136 - 76) * factor, (144 - 76) * factor, (144 - 76) * factor)
            )
        ]

    client.crop_boxes = crop_boxes
    # Rebuild the stills at 400 px so the numbers above are exact.
    for suffix in ("01.png", "01_before.png", "01_after.png"):
        image = np.full((400, 400, 3), 120, dtype=np.uint8)
        assert cv2.imwrite(str(tmp_path / "stills" / suffix), image)
    result = perception.run(tmp_path, settings, client=client)

    (record,) = result.steps[0].removed
    assert record.box.x * 400 == pytest.approx(136, abs=1)
    assert record.box.y * 400 == pytest.approx(136, abs=1)
    assert record.box.w * 400 == pytest.approx(8, abs=1)


def test_nms_drops_duplicate_screws(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=1)])
    duplicate = (0.20, 0.20, 0.05, 0.05)
    client = FakeClient(part=PART, before={"01": [duplicate, duplicate]}, after={"01": []})
    result = perception.run(tmp_path, settings, client=client)
    assert result.steps[0].screws_before == 1
    assert len(result.steps[0].removed) == 1


def test_note_when_sam_and_analysis_counts_differ(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=4)])
    client = FakeClient(part=PART, before={"01": FOUR[:3]}, after={"01": []})
    result = perception.run(tmp_path, settings, client=client)
    assert "SAM found 3 screws removed, the analysis counted 4." in result.steps[0].notes


def test_no_part_uses_whole_frame_and_notes_it(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=1)])
    client = FakeClient(part={}, before={"01": [FOUR[0]]}, after={"01": []})
    result = perception.run(tmp_path, settings, client=client)
    step = result.steps[0]
    assert step.part is None
    assert "No part found for 'battery'." in step.notes
    assert len(step.removed) == 1


def test_max_steps_and_budget(tmp_path):
    steps = [_step(i, (i - 1) * 4.0, i * 4.0, screws=1) for i in range(1, 14)]
    settings = _job(tmp_path, steps)
    client = FakeClient(
        part=PART,
        before={f"{i:02d}": [FOUR[0]] for i in range(1, 14)},
        after={},
    )
    result = perception.run(tmp_path, settings, client=client)
    assert len(result.steps) == perception.MAX_STEPS
    assert [step.index for step in result.steps] == list(range(1, 13))

    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=1), _step(2, 5.0, 10.0, screws=1)])
    client = FakeClient(
        part=PART,
        before={"01": [FOUR[0]], "02": [FOUR[0]]},
        after={},
        fail_on_call=5,
    )
    result = perception.run(tmp_path, settings, client=client)
    # Step 1 finished (3 calls); step 2 made its part call, then the budget
    # stopped the screw calls. Earlier results survive.
    assert len(result.steps[0].removed) == 1
    assert result.steps[1].part is not None
    assert "SAM budget reached." in result.steps[1].notes
    assert result.sam_calls == 5


def test_meta_error_on_one_step_keeps_the_others(tmp_path):
    steps = [_step(1, 0.0, 5.0, screws=1), _step(2, 5.0, 10.0, screws=1)]
    settings = _job(tmp_path, steps)
    client = FakeClient(
        part=PART,
        before={"01": [FOUR[0]], "02": [FOUR[0]]},
        after={},
        meta_fail_on_call=1,
    )
    result = perception.run(tmp_path, settings, client=client)
    assert result.steps[0].notes
    assert len(result.steps[1].removed) == 1


SCREW_CENTRES = [(150, 140), (450, 140), (150, 340), (450, 340)]


class BlobClient:
    """Fake SAM that finds the bright screw circles in the image it receives."""

    def __init__(self):
        self.calls = []

    def segment(self, image_path, concept, max_side=1280):
        image = cv2.imread(str(image_path))
        assert image is not None
        height, width = image.shape[:2]
        self.calls.append((image_path.name, concept, (width, height)))
        if concept != "screw":
            return [], (width, height)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections = []
        for contour in contours:
            if not 20 <= cv2.contourArea(contour) <= 2000:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            detections.append(_det((x, y, x + w, y + h), 0.9))
        return detections, (width, height)


def _textured_stills():
    """Before/after stills: after is shifted/rotated, with the first screw removed."""
    rng = np.random.default_rng(7)
    base = np.full((480, 640, 3), 120, dtype=np.uint8)
    for _ in range(500):
        x = int(rng.integers(0, 630))
        y = int(rng.integers(0, 470))
        side = int(rng.integers(3, 9))
        shade = int(rng.integers(20, 80))
        cv2.rectangle(base, (x, y), (x + side, y + side), (shade, shade, shade), -1)
    before = base.copy()
    for cx, cy in SCREW_CENTRES:
        cv2.circle(before, (cx, cy), 6, (240, 240, 240), -1)
    after_base = base.copy()
    for cx, cy in SCREW_CENTRES[1:]:
        cv2.circle(after_base, (cx, cy), 6, (240, 240, 240), -1)
    forward = cv2.getRotationMatrix2D((320.0, 240.0), 3.0, 1.0)
    forward[0, 2] += 60.0
    forward[1, 2] += 25.0
    after = cv2.warpAffine(after_base, forward, (640, 480), borderValue=(120, 120, 120))
    return before, after, forward


def _alignment_job(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=4)])
    before, after, forward = _textured_stills()
    for name, image in (
        ("01.png", before),
        ("01_before.png", before),
        ("01_after.png", after),
    ):
        assert cv2.imwrite(str(tmp_path / "stills" / name), image)
    return settings, before, after, forward


def test_alignment_recovers_shifted_rotated_after_still(tmp_path, monkeypatch):
    settings, before, after, forward = _alignment_job(tmp_path / "aligned")
    matrix = perception.align_after_to_before(before, after)
    assert matrix is not None
    expected = cv2.invertAffineTransform(forward)
    before_pts = np.float32(SCREW_CENTRES).reshape(-1, 1, 2)
    after_pts = cv2.transform(before_pts, forward)
    estimated = cv2.transform(after_pts, matrix).reshape(-1, 2)
    truth = cv2.transform(after_pts, expected).reshape(-1, 2)
    errors = np.linalg.norm(estimated - truth, axis=1)
    assert float(errors.max()) < 5.0

    result = perception.run(tmp_path / "aligned", settings, client=BlobClient())
    step = result.steps[0]
    assert len(step.removed) == 1
    (record,) = step.removed
    centre = (record.box.x + record.box.w / 2, record.box.y + record.box.h / 2)
    assert centre == pytest.approx((150 / 640, 140 / 480), abs=0.02)
    assert "Camera moved too much to verify the screws." not in step.notes

    # Without alignment the same stills must give more removed screws,
    # so this test would catch the original hand-held-camera problem.
    settings2, _, _, _ = _alignment_job(tmp_path / "unaligned")
    monkeypatch.setattr(perception, "align_after_to_before", lambda *_args: None)
    result2 = perception.run(tmp_path / "unaligned", settings2, client=BlobClient())
    assert len(result2.steps[0].removed) > 1


def test_alignment_failure_notes_and_caps_confidence(tmp_path):
    settings, before, _, _ = _alignment_job(tmp_path)
    featureless = np.full((480, 640, 3), 120, dtype=np.uint8)
    assert perception.align_after_to_before(before, featureless) is None
    assert cv2.imwrite(str(tmp_path / "stills" / "01_after.png"), featureless)

    result = perception.run(tmp_path, settings, client=BlobClient())
    step = result.steps[0]
    assert "Camera moved too much to verify the screws." in step.notes
    assert step.removed
    assert all(
        record.confidence is not None and record.confidence <= 0.5 for record in step.removed
    )


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


def _write_identity(job_dir, category="automotive", **fields):
    data = {"object_name": "sedan", "category": category, "task": "repair"}
    data.update(fields)
    (job_dir / "identity.json").write_text(json.dumps(data), encoding="utf-8")


def _ledger_concepts(client):
    return {concept for name, concept, _ in client.calls if "before" in name or "after" in name}


def test_automotive_identity_ledger_uses_bolt(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=1)])
    _write_identity(tmp_path, problem="brakes squeak")
    client = FakeClient(part=PART, before={"01": [FOUR[0]]}, after={"01": []})

    result = perception.run(tmp_path, settings, client=client)

    assert perception.fastener_concept(tmp_path) == "bolt"
    assert _ledger_concepts(client) == {"bolt"}
    assert len(result.steps[0].removed) == 1


def test_no_identity_ledger_uses_screw(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=1)])
    client = FakeClient(part=PART, before={"01": [FOUR[0]]}, after={"01": []})

    result = perception.run(tmp_path, settings, client=client)

    assert perception.fastener_concept(tmp_path) == "screw"
    assert _ledger_concepts(client) == {"screw"}
    assert len(result.steps[0].removed) == 1


def test_automotive_notes_use_bolts(tmp_path):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=2)])
    _write_identity(tmp_path)
    client = FakeClient(part=PART, before={"01": [FOUR[0]]}, after={"01": []})

    result = perception.run(tmp_path, settings, client=client)

    assert "SAM found 1 bolts removed, the analysis counted 2." in result.steps[0].notes


def test_automotive_alignment_failure_note_uses_bolts(tmp_path, monkeypatch):
    settings = _job(tmp_path, [_step(1, 0.0, 5.0, screws=1)])
    _write_identity(tmp_path)
    client = FakeClient(part=PART, before={"01": [FOUR[0]]}, after={"01": []})
    monkeypatch.setattr(perception, "align_after_to_before", lambda *_args: None)

    result = perception.run(tmp_path, settings, client=client)

    assert "Camera moved too much to verify the bolts." in result.steps[0].notes


def test_part_concepts_prefer_plain_words_then_the_head_noun():
    from app.pipeline.perception import part_concepts
    from app.schemas import Step

    step = Step(index=1, title="t", instruction="i", start_s=0, end_s=1, sam_concept="wooden leg",
                target_part="leg frame C", removes=["Rail C"])  # fmt: skip
    assert part_concepts(step) == ["wooden leg", "leg", "frame c"]
