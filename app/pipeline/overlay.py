"""Draw SAM highlights and numbered screw markers on a keyframe."""

import os
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.meta_client import Detection

# Signal lime #D4FF3A and graphite #0E0F11, in OpenCV BGR order.
LIME_BGR = (58, 255, 212)
GRAPHITE_BGR = (17, 15, 14)
WHITE_BGR = (255, 255, 255)


def normalize(
    box: tuple[float, float, float, float], size: tuple[int, int]
) -> tuple[float, float, float, float]:
    """Convert a pixel box to 0..1 coordinates, clamped to the image."""
    width, height = size
    if width <= 0 or height <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    left, top, right, bottom = box
    return (
        min(1.0, max(0.0, left / width)),
        min(1.0, max(0.0, top / height)),
        min(1.0, max(0.0, right / width)),
        min(1.0, max(0.0, bottom / height)),
    )


def _scaled_box(
    box: tuple[float, float, float, float],
    size_sent: tuple[int, int],
    image_shape: tuple[int, ...],
) -> tuple[int, int, int, int]:
    img_h, img_w = image_shape[:2]
    sent_w, sent_h = size_sent
    scale_x = img_w / sent_w if sent_w else 1.0
    scale_y = img_h / sent_h if sent_h else 1.0
    left, top, right, bottom = box
    x1 = min(img_w, max(0, round(left * scale_x)))
    y1 = min(img_h, max(0, round(top * scale_y)))
    x2 = min(img_w, max(0, round(right * scale_x)))
    y2 = min(img_h, max(0, round(bottom * scale_y)))
    return x1, y1, x2, y2


def _rounded_rectangle(image: Any, pt1: tuple[int, int], pt2: tuple[int, int]) -> None:
    x1, y1 = pt1
    x2, y2 = pt2
    if x2 <= x1 or y2 <= y1:
        cv2.rectangle(image, pt1, pt2, LIME_BGR, 2)
        return
    radius = max(1, min(12, (x2 - x1) // 2, (y2 - y1) // 2))
    cv2.line(image, (x1 + radius, y1), (x2 - radius, y1), LIME_BGR, 2)
    cv2.line(image, (x1 + radius, y2), (x2 - radius, y2), LIME_BGR, 2)
    cv2.line(image, (x1, y1 + radius), (x1, y2 - radius), LIME_BGR, 2)
    cv2.line(image, (x2, y1 + radius), (x2, y2 - radius), LIME_BGR, 2)
    cv2.ellipse(image, (x1 + radius, y1 + radius), (radius, radius), 180, 0, 90, LIME_BGR, 2)
    cv2.ellipse(image, (x2 - radius, y1 + radius), (radius, radius), 270, 0, 90, LIME_BGR, 2)
    cv2.ellipse(image, (x2 - radius, y2 - radius), (radius, radius), 0, 0, 90, LIME_BGR, 2)
    cv2.ellipse(image, (x1 + radius, y2 - radius), (radius, radius), 90, 0, 90, LIME_BGR, 2)


def draw_part(image: Any, detection: Detection, size_sent: tuple[int, int]) -> Any:
    """Return a copy with the part mask tinted lime, or a lime box outline."""
    result = image.copy()
    if detection.mask is None:
        x1, y1, x2, y2 = _scaled_box(detection.box, size_sent, image.shape)
        _rounded_rectangle(result, (x1, y1), (x2, y2))
        return result
    bounds = detection.mask_bounds if detection.mask_bounds is not None else detection.box
    x1, y1, x2, y2 = _scaled_box(bounds, size_sent, image.shape)
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    if detection.mask_size is None:
        inferred_w = max(1, int(round(bounds[2] - bounds[0])))
        inferred_h = max(1, int(round(bounds[3] - bounds[1])))
        if len(detection.mask) < inferred_w * inferred_h:
            _rounded_rectangle(result, (x1, y1), (x2, y2))
            return result
        mask_w, mask_h = inferred_w, inferred_h
    else:
        mask_w, mask_h = detection.mask_size
    if mask_w <= 0 or mask_h <= 0 or len(detection.mask) < mask_w * mask_h:
        _rounded_rectangle(result, (x1, y1), (x2, y2))
        return result
    local = np.frombuffer(detection.mask[: mask_w * mask_h], dtype=np.uint8).reshape(mask_h, mask_w)
    scaled = cv2.resize(local, (box_w, box_h), interpolation=cv2.INTER_NEAREST)
    full = np.zeros(image.shape[:2], dtype=np.uint8)
    full[y1:y2, x1:x2] = (scaled > 0).astype(np.uint8) * 255
    lime = np.array(LIME_BGR, dtype=np.float32)
    region = full > 0
    if np.any(region):
        original = result[region].astype(np.float32)
        result[region] = (original * 0.65 + lime * 0.35).astype(np.uint8)
        contours, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(result, contours, -1, LIME_BGR, 2)
    return result


def _box_of(item: Any) -> tuple[float, float, float, float]:
    box = getattr(item, "box", item)
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def draw_screws(image: Any, boxes: Any, numbers: Any) -> Any:
    """Return a copy with a numbered graphite marker at each box center."""
    result = image.copy()
    for item, number in zip(boxes, numbers, strict=False):
        left, top, right, bottom = _box_of(item)
        center_x = int(round((left + right) / 2))
        center_y = int(round((top + bottom) / 2))
        box_size = max(right - left, bottom - top)
        radius = max(14, int(round(box_size / 2)))
        overlay = result.copy()
        cv2.circle(overlay, (center_x, center_y), radius, GRAPHITE_BGR, -1)
        circle_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.circle(circle_mask, (center_x, center_y), radius, 255, -1)
        region = circle_mask > 0
        if np.any(region):
            blended = (
                overlay[region].astype(np.float32) * 0.85 + result[region].astype(np.float32) * 0.15
            )
            result[region] = blended.astype(np.uint8)
        cv2.circle(result, (center_x, center_y), radius, LIME_BGR, 2)
        label = str(number)
        font_scale = max(0.5, min(1.0, radius / 22.0))
        thickness = 2
        (text_w, text_h), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        origin = (center_x - text_w // 2, center_y + text_h // 2)
        cv2.putText(
            result,
            label,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            WHITE_BGR,
            thickness,
            cv2.LINE_AA,
        )
    return result


def save_jpeg(image: Any, path: Path, quality: int = 88) -> None:
    """Write a JPEG atomically via a temp file in the same folder."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False, suffix=".jpg") as tmp:
            tmp_path = tmp.name
        if not cv2.imwrite(tmp_path, image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]):
            raise OSError(f"cannot write image: {path}")
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
