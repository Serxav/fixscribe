"""Overlay tests on synthetic images only."""

import cv2
import numpy as np

from app.meta_client import Detection
from app.pipeline.overlay import draw_part, draw_screws, normalize, save_jpeg


def _gray(width=200, height=200, value=120):
    return np.full((height, width, 3), value, dtype=np.uint8)


def test_normalize_clamps():
    assert normalize((50, 50, 150, 100), (200, 200)) == (0.25, 0.25, 0.75, 0.5)
    assert normalize((-10, -10, 300, 300), (200, 200)) == (0.0, 0.0, 1.0, 1.0)


def test_draw_screws_changes_center_and_leaves_corner():
    image = _gray()
    original = image.copy()
    result = draw_screws(image, [(40, 40, 60, 60), (140, 140, 160, 160)], [1, 2])

    assert not np.array_equal(result[50, 50], original[50, 50])
    assert not np.array_equal(result[150, 150], original[150, 150])
    assert np.array_equal(result[0, 0], original[0, 0])
    assert np.array_equal(image, original)


def test_draw_screws_accepts_detections_and_labels():
    image = _gray()
    detections = [
        Detection(
            object_id="0",
            box=(40.0, 40.0, 60.0, 60.0),
            confidence=None,
            mask=None,
            mask_size=None,
            mask_bounds=None,
        )
    ]
    result = draw_screws(image, detections, ["S1"])
    assert not np.array_equal(result[50, 50], image[50, 50])
    assert np.array_equal(result[0, 0], image[0, 0])


def test_draw_part_without_mask_draws_outline():
    image = _gray()
    detection = Detection(
        object_id="0",
        box=(40.0, 40.0, 120.0, 120.0),
        confidence=None,
        mask=None,
        mask_size=None,
        mask_bounds=None,
    )
    result = draw_part(image, detection, (200, 200))

    # Top edge of the box is drawn, interior and far corner stay gray.
    assert not np.array_equal(result[40, 80], image[40, 80])
    assert np.array_equal(result[80, 80], image[80, 80])
    assert np.array_equal(result[0, 0], image[0, 0])
    assert np.array_equal(image, _gray())


def test_draw_part_with_mask_tints_mask_area():
    image = _gray()
    mask = bytes([1] * 16)
    detection = Detection(
        object_id="0",
        box=(40.0, 40.0, 44.0, 44.0),
        confidence=None,
        mask=mask,
        mask_size=(4, 4),
        mask_bounds=(40.0, 40.0, 44.0, 44.0),
    )
    result = draw_part(image, detection, (200, 200))

    assert not np.array_equal(result[42, 42], image[42, 42])
    assert np.array_equal(result[0, 0], image[0, 0])
    assert np.array_equal(image, _gray())


def test_draw_part_scales_from_sent_size():
    image = _gray(width=400, height=400)
    detection = Detection(
        object_id="0",
        box=(20.0, 20.0, 60.0, 60.0),
        confidence=None,
        mask=None,
        mask_size=None,
        mask_bounds=None,
    )
    result = draw_part(image, detection, (200, 200))
    # Box doubles when the real image is twice the sent size.
    assert not np.array_equal(result[40, 80], image[40, 80])
    assert np.array_equal(result[0, 0], image[0, 0])


def test_save_jpeg_atomic_no_temp_file(tmp_path):
    image = _gray(width=50, height=50)
    target = tmp_path / "out.jpg"

    save_jpeg(image, target)

    assert target.is_file()
    loaded = cv2.imread(str(target))
    assert loaded is not None
    assert loaded.shape == (50, 50, 3)
    leftovers = [p for p in tmp_path.iterdir() if p.name != "out.jpg"]
    assert leftovers == []
