"""Second look: Muse Spark checks every candidate part on a zoomed contact sheet.

Detections (Spark grounding or SAM 3.1) are each shown as one numbered, zoomed tile with the
candidate framed in green and its exact cut-out traced in magenta. Spark answers, per tile,
whether it really is that part; only confirmed candidates are kept. Used by the perception
stage (fasteners on video stills) and by scripts/make_photos.py (landing photos).
Boxes and outlines use the 0..1000 grid of the image.
"""

import base64
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.meta_client import MetaError

CHECK_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "check_marks_v1.md"
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


def contact_sheet(image: np.ndarray, marks: list[dict]) -> np.ndarray:
    """One zoomed, numbered tile per mark with the cut-out framed in green, checked one by one."""
    height, width = image.shape[:2]
    pad = max(height, width) // 4
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(40, 40, 40))
    tiles = []
    for n, mark in enumerate(marks, start=1):
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
        tile = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_CUBIC)
        corner1 = (int((x1 + pad - left) * scale) - 3, int((y1 + pad - top) * scale) - 3)
        corner2 = (int((x2 + pad - left) * scale) + 3, int((y2 + pad - top) * scale) + 3)
        cv2.rectangle(tile, corner1, corner2, (0, 220, 0), 2)
        if mark.get("outline"):
            shape = [
                [(x * width / 1000 + pad - left) * scale, (y * height / 1000 + pad - top) * scale]
                for x, y in mark["outline"]
            ]
            cv2.polylines(tile, [np.array(shape, np.int32)], True, (255, 0, 255), 2)
        caption = np.full((34, TILE, 3), 255, dtype=np.uint8)
        cv2.putText(caption, f"{n}: {mark['label']}"[:28], (6, 24), 0, 0.62, (0, 0, 0), 2)
        tiles.append(np.vstack([tile, caption]))
    columns = min(4, len(tiles))
    blank = np.full_like(tiles[0], 255)
    while len(tiles) % columns:
        tiles.append(blank)
    rows = [np.hstack(tiles[i : i + columns]) for i in range(0, len(tiles), columns)]
    return np.vstack(rows)


def confirm(
    client: Any, model: str, image: np.ndarray, marks: list[dict], context: str
) -> list[dict]:
    """Ask Spark to check each mark on a zoomed contact sheet; keep the confirmed ones."""
    if not marks:
        return marks
    ok, buffer = cv2.imencode(".jpg", contact_sheet(image, marks), [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise MetaError("cannot encode the contact sheet")
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")
    labels = ", ".join(sorted({mark["label"] for mark in marks}))
    prompt = (
        CHECK_PROMPT.read_text(encoding="utf-8")
        .replace("<<CONTEXT>>", context)
        .replace("<<LABELS>>", labels)
    )
    response = client.respond(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
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
    verdicts = {a["n"]: a for a in answers if isinstance(a, dict) and isinstance(a.get("n"), int)}
    for n, mark in enumerate(marks, start=1):
        verdict = verdicts.get(n, {})
        mark["checked"] = verdict.get("real") is True
        mark["why"] = str(verdict.get("why", "not answered"))
    return marks
