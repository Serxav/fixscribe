"""Second look: Muse Spark checks every candidate part on zoomed, numbered tiles.

Spark never gives coordinates here (set-of-mark prompting): each candidate (found by SAM 3.1 or
by Spark grounding) is shown as a numbered, zoomed tile with the candidate framed in green and,
when known, its exact cut-out traced in magenta. Spark answers, per number, whether it really
is that part; only confirmed candidates are kept.

- ``confirm``: one tile per candidate, all from one image (scripts/make_photos.py).
- ``confirm_tracks``: one image per candidate with up to three tiles of it from different
  frames of a video, so a fastener is judged on several views, not on one blurry frame
  (the fastener method in app/pipeline/fasteners.py).

Boxes and outlines use the 0..1000 grid of the image they are on.
"""

import base64
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.meta_client import MetaError

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
CHECK_PROMPT = PROMPTS / "check_marks_v1.md"
TRACK_PROMPT = PROMPTS / "check_tracks_v1.md"
TILE = 300
MAX_TILES = 16

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "tiles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "real": {"type": "boolean"},
                    "why": {"type": "string"},
                },
                "required": ["n", "real", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tiles"],
    "additionalProperties": False,
}


def tile(image: np.ndarray, mark: dict, caption: str) -> np.ndarray:
    """One zoomed tile of ``mark`` on ``image``: green frame, magenta outline, a caption."""
    height, width = image.shape[:2]
    pad = max(height, width) // 4
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(40, 40, 40))
    bx1, by1, bx2, by2 = mark["cut_box"]
    x1, y1 = bx1 * width / 1000, by1 * height / 1000
    x2, y2 = bx2 * width / 1000, by2 * height / 1000
    size = max(x2 - x1, y2 - y1, 0.02 * min(width, height))
    # small parts get room around them; big parts fill the tile so they stay recognisable
    side = min(max(size * 1.4, min(size * 3, 0.25 * max(width, height))), max(width, height))
    cx, cy = (x1 + x2) / 2 + pad, (y1 + y2) / 2 + pad
    left, top = max(0, int(cx - side / 2)), max(0, int(cy - side / 2))
    crop = padded[top : top + int(side), left : left + int(side)]
    scale = TILE / crop.shape[1]
    out = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_CUBIC)
    corner1 = (int((x1 + pad - left) * scale) - 3, int((y1 + pad - top) * scale) - 3)
    corner2 = (int((x2 + pad - left) * scale) + 3, int((y2 + pad - top) * scale) + 3)
    cv2.rectangle(out, corner1, corner2, (0, 220, 0), 2)
    if mark.get("outline"):
        shape = [
            [(x * width / 1000 + pad - left) * scale, (y * height / 1000 + pad - top) * scale]
            for x, y in mark["outline"]
        ]
        cv2.polylines(out, [np.array(shape, np.int32)], True, (255, 0, 255), 2)
    strip = np.full((34, TILE, 3), 255, dtype=np.uint8)
    cv2.putText(strip, caption[:28], (6, 24), 0, 0.62, (0, 0, 0), 2)
    return np.vstack([out, strip])


def contact_sheet(image: np.ndarray, marks: list[dict]) -> np.ndarray:
    """One zoomed, numbered tile per mark, four to a row."""
    tiles = [tile(image, mark, f"{n}: {mark['label']}") for n, mark in enumerate(marks, start=1)]
    columns = min(4, len(tiles))
    blank = np.full_like(tiles[0], 255)
    while len(tiles) % columns:
        tiles.append(blank)
    rows = [np.hstack(tiles[i : i + columns]) for i in range(0, len(tiles), columns)]
    return np.vstack(rows)


def _data_url(image: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise MetaError("cannot encode a check image")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")


def _ask(client: Any, model: str, prompt: str, images: list[np.ndarray]) -> dict[int, dict]:
    """Send the prompt and the images; return Spark's verdict per number."""
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": _data_url(image)} for image in images]
    response = client.respond(
        model=model,
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "check",
                "schema": CHECK_SCHEMA,
                "strict": True,
            }
        },
        reasoning={"effort": "medium"},
        max_output_tokens=4000,
    )
    try:
        answers = json.loads(response.output_text)["tiles"]
    except (ValueError, TypeError, KeyError):
        raise MetaError("the check returned invalid JSON") from None
    return {a["n"]: a for a in answers if isinstance(a, dict) and isinstance(a.get("n"), int)}


def _apply(marks: list[dict], verdicts: dict[int, dict]) -> list[dict]:
    for n, mark in enumerate(marks, start=1):
        verdict = verdicts.get(n, {})
        mark["checked"] = verdict.get("real") is True
        mark["why"] = str(verdict.get("why", "not answered"))
    return marks


def _prompt(path: Path, context: str, labels: str) -> str:
    return (
        path.read_text(encoding="utf-8")
        .replace("<<CONTEXT>>", context)
        .replace("<<LABELS>>", labels)
    )


def confirm(
    client: Any, model: str, image: np.ndarray, marks: list[dict], context: str
) -> list[dict]:
    """Ask Spark to check each mark on a zoomed contact sheet; mark the confirmed ones."""
    if not marks:
        return marks
    labels = ", ".join(sorted({mark["label"] for mark in marks}))
    verdicts = _ask(
        client, model, _prompt(CHECK_PROMPT, context, labels), [contact_sheet(image, marks)]
    )
    return _apply(marks, verdicts)


def confirm_tracks(client: Any, model: str, marks: list[dict], context: str) -> list[dict]:
    """Ask Spark to check each followed candidate on several frames; mark the confirmed ones.

    Each mark has ``label`` and ``views``: up to three ``(frame image, cut_box)`` pairs of the
    same candidate. Image n of the request shows candidate n, its views side by side.
    """
    if not marks:
        return marks
    images = []
    for n, mark in enumerate(marks, start=1):
        views = mark["views"][:3]
        tiles = [
            tile(image, {"cut_box": box}, f"{n}: {mark['label']} ({k}/{len(views)})")
            for k, (image, box) in enumerate(views, start=1)
        ]
        images.append(np.hstack(tiles))
    labels = ", ".join(sorted({mark["label"] for mark in marks}))
    verdicts = _ask(client, model, _prompt(TRACK_PROMPT, context, labels), images)
    return _apply(marks, verdicts)
