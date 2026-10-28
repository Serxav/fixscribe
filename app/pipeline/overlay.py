"""Draw SAM highlights and numbered screw markers on a keyframe."""

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import artifacts
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


def _is_norm_box(item: Any) -> bool:
    return all(hasattr(item, name) for name in ("x", "y", "w", "h"))


def _pixel_box(
    item: Any, image_shape: tuple[int, ...], size_sent: tuple[int, int] | None
) -> tuple[int, int, int, int]:
    """Resolve a screw box to pixel ``(left, top, right, bottom)`` on the image.

    Accepts a normalized box (``x, y, w, h`` attributes, or an object whose
    ``box`` holds one), a detection/pixel box in the ``size_sent`` image, or a
    plain pixel box in image coordinates. Normalized tuples (all values in
    0..1) are read as ``(left, top, right, bottom)`` fractions of the image.
    """
    img_h, img_w = image_shape[:2]
    carrier = item
    box = getattr(item, "box", item)
    if _is_norm_box(box):
        left = float(box.x) * img_w
        top = float(box.y) * img_h
        return (
            int(round(left)),
            int(round(top)),
            int(round(left + float(box.w) * img_w)),
            int(round(top + float(box.h) * img_h)),
        )
    if _is_norm_box(carrier):
        left = float(carrier.x) * img_w
        top = float(carrier.y) * img_h
        return (
            int(round(left)),
            int(round(top)),
            int(round(left + float(carrier.w) * img_w)),
            int(round(top + float(carrier.h) * img_h)),
        )
    values = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    if size_sent is not None and max(values, key=abs) > 1.0:
        return _scaled_box(values, size_sent, image_shape)
    if max(values, key=abs) <= 1.0:
        left, top, right, bottom = values
        return (
            int(round(left * img_w)),
            int(round(top * img_h)),
            int(round(right * img_w)),
            int(round(bottom * img_h)),
        )
    x1 = min(img_w, max(0, int(round(values[0]))))
    y1 = min(img_h, max(0, int(round(values[1]))))
    x2 = min(img_w, max(0, int(round(values[2]))))
    y2 = min(img_h, max(0, int(round(values[3]))))
    return x1, y1, x2, y2


def _label_of(number: Any) -> str:
    for attr in ("id", "number"):
        value = getattr(number, attr, None)
        if value is not None and not isinstance(number, int | str):
            return str(value)
    return str(number)


def draw_screws(
    image: Any,
    boxes: Any,
    numbers: Any,
    size_sent: tuple[int, int] | None = None,
) -> Any:
    """Return a copy with a ring around each screw and its number beside it.

    Boxes follow the same contract as :func:`draw_part`: normalized boxes, or
    pixel boxes in an image of ``size_sent`` (the image itself when omitted).
    The screw centre is never painted over: a hollow ring marks the screw and
    a graphite label with a lime outline sits up-right of it, joined by a thin
    leader line that starts at the ring, not at the centre. Everything scales
    with the image (a 720p still gets marks twice as thick as a 640 px one),
    and each ring has a graphite halo so it stays visible on light wood.
    """
    result = image.copy()
    img_h, img_w = image.shape[:2]
    unit = max(1, round(max(img_w, img_h) / 640))
    min_radius = max(6, round(0.012 * float(np.hypot(img_w, img_h))))
    for item, number in zip(boxes, numbers, strict=False):
        x1, y1, x2, y2 = _pixel_box(item, image.shape, size_sent)
        if x2 <= x1 or y2 <= y1:
            continue
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        diagonal = float(np.hypot(x2 - x1, y2 - y1))
        radius = max(min_radius, int(round(0.6 * diagonal)))
        cv2.circle(result, (center_x, center_y), radius, GRAPHITE_BGR, 2 * unit + 2, cv2.LINE_AA)
        cv2.circle(result, (center_x, center_y), radius, LIME_BGR, 2 * unit, cv2.LINE_AA)
        label = _label_of(number)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5 * unit
        thickness = unit
        (text_w, text_h), _ = cv2.getTextSize(label, font, font_scale, thickness)
        label_radius = max(10 * unit, text_w // 2 + 6 * unit, text_h // 2 + 6 * unit)
        offset = radius + label_radius + 6 * unit
        label_x, label_y = center_x + offset, center_y - offset
        # Prefer up-right; fall back to another side so the label stays
        # inside the image and never covers the screw it names.
        for step_x, step_y in (
            (1, -1),
            (-1, -1),
            (1, 1),
            (-1, 1),
            (1, 0),
            (-1, 0),
            (0, -1),
            (0, 1),
        ):
            cand_x = center_x + step_x * offset
            cand_y = center_y + step_y * offset
            if (
                label_radius <= cand_x <= img_w - 1 - label_radius
                and label_radius <= cand_y <= img_h - 1 - label_radius
            ):
                label_x, label_y = cand_x, cand_y
                break
        else:
            if img_w > 2 * label_radius:
                label_x = min(max(label_x, label_radius), img_w - 1 - label_radius)
            else:
                label_x = img_w // 2
            if img_h > 2 * label_radius:
                label_y = min(max(label_y, label_radius), img_h - 1 - label_radius)
            else:
                label_y = img_h // 2
        dx = label_x - center_x
        dy = label_y - center_y
        distance = float(np.hypot(dx, dy))
        if distance > radius + label_radius + 1:
            unit_x, unit_y = dx / distance, dy / distance
            start = (
                int(round(center_x + unit_x * (radius + 1))),
                int(round(center_y + unit_y * (radius + 1))),
            )
            end = (
                int(round(label_x - unit_x * (label_radius + 1))),
                int(round(label_y - unit_y * (label_radius + 1))),
            )
            cv2.line(result, start, end, LIME_BGR, unit, cv2.LINE_AA)
        cv2.circle(result, (label_x, label_y), label_radius, GRAPHITE_BGR, -1, cv2.LINE_AA)
        cv2.circle(result, (label_x, label_y), label_radius, LIME_BGR, 2 * unit, cv2.LINE_AA)
        origin = (label_x - text_w // 2, label_y + text_h // 2)
        cv2.putText(result, label, origin, font, font_scale, WHITE_BGR, thickness, cv2.LINE_AA)
    return result


def save_jpeg(image: Any, path: Path, quality: int = 88) -> None:
    """Write a JPEG atomically via a temp file in the same folder."""
    path = Path(path)
    with artifacts.atomic_path(path) as tmp_path:
        if not cv2.imwrite(str(tmp_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]):
            raise OSError(f"cannot write image: {path}")
