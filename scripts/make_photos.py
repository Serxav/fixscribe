"""Make the landing photos with Meta models and mark them with the real pipeline.

Run: ``python -m scripts.make_photos --only phone engine --cap 2.0`` (no ``--only``: every subject).

For each subject Muse Image draws a realistic workshop photo, Muse Spark grounds the parts
FixScribe would look for (0..1000 grid) and SAM 3.1 cuts each grounded box out. Weak cut-outs
are dropped, then Spark checks every remaining mark again on a zoomed contact sheet and only the
confirmed ones are kept. The page draws its boxes and outlines from these answers, never from
hand-placed marks. Writes web/static/photos/<name>.webp and <name>.json. Spend is capped by
``--cap`` (USD) through the client's own counter in data/web_photos/.
"""

import argparse
import base64
import dataclasses
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from app.agent.tools import full_mask
from app.config import get_settings
from app.meta_client import BudgetExceeded, MetaClient, MetaError

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "static" / "photos"
CHECK_PROMPT = ROOT / "prompts" / "check_marks_v1.md"

MIN_CONFIDENCE = 0.3
SMALL_PART = 100  # boxes narrower than this (0..1000 grid) are found again on a close-up
MIN_FILL = 0.2
TILE = 300

STYLE = (
    "Realistic documentary photograph taken in a real repair workshop. Natural soft daylight, "
    "true colors, sharp focus, shallow depth of field, slight film grain. Shot on a 35mm lens. "
    "No text, no captions, no watermarks, no brand logos, no faces."
)

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

# "refused": the safety rules give no steps for this job; its marks show the hazards found.
SUBJECTS: dict[str, dict[str, str]] = {
    "laptop": {
        "prompt": "Top-down view of a laptop lying upside down on a dark desk mat, its bottom "
        "panel with eight small black Phillips screws clearly visible around the edges, a "
        "precision screwdriver beside it.",
        "query": "each screw on the bottom panel",
        "context": "A laptop being opened from the bottom.",
    },
    "chair": {
        "prompt": "Office chair turned upside down on a workshop floor, the five-star base and the "
        "chrome gas lift cylinder clearly visible in the middle, a rubber mallet beside it.",
        "query": "the chrome gas lift cylinder",
        "context": "An office chair whose gas lift is being replaced.",
    },
    "bike": {
        "prompt": "Close view of a bicycle's rear wheel on a repair stand, the chain, the cassette "
        "and the rear derailleur clearly visible, a chain tool hanging nearby.",
        "query": "the rear derailleur and the cassette",
        "min_fill": "0.05",
        "context": "A bicycle drivetrain being serviced.",
    },
    "engine": {
        "prompt": "Three-quarter view of a small four-cylinder car engine on an engine stand in a "
        "tidy garage, the valve cover bolts clearly visible on top, the spark plug wells exposed, "
        "a socket wrench resting on the bench beside it.",
        "query": "each threaded stud sticking up from the top of the cylinder head",
        "inventory": "the cylinder head, the engine block, the engine stand, each intake port "
        "on the side and the socket wrench on the bench",
        "context": "A bare engine block with its cylinder head on a stand, being rebuilt.",
    },
    "washer": {
        "prompt": "Front-loading washing machine in a laundry room, the small service flap at the "
        "bottom front open, showing the round drain pump filter cap, a shallow tray on the floor.",
        "query": "the round drain filter cap",
        "context": "A washing machine whose drain filter is being cleaned.",
    },
    "panel": {
        "prompt": "Residential electrical distribution panel on a wall with its front cover "
        "removed, rows of circuit breakers and wiring visible.",
        "query": "the main breaker and each row of circuit breakers",
        "context": "A live mains distribution panel: a job for a licensed electrician only.",
        "refused": "yes",
    },
    "drone": {
        "prompt": "Top-down view of a quadcopter drone on a wooden workbench with its top shell "
        "removed, four brushless motors at the arm tips, propellers taken off and laid beside it, "
        "the battery pack in the middle and small screws in a magnetic tray.",
        "query": "the battery pack and the round motor bell at the tip of each of the four arms "
        "(only the motor, not the landing leg below it)",
        "min_fill": "0.1",
        "context": "A drone being opened to replace a motor.",
    },
    "faucet": {
        "prompt": "Kitchen sink faucet with its lever handle removed and set aside, the brass "
        "cartridge exposed in the body, an adjustable wrench on the counter.",
        "query": "the exposed faucet cartridge",
        "context": "A leaking faucet whose cartridge is being replaced.",
    },
    "wheel": {
        "prompt": "Close view of a car wheel with five lug nuts while the car is raised on a jack "
        "in a driveway, a lug wrench resting against the tire.",
        "query": "the wheel hub with its lug nuts",
        "zoom_into": "hub",
        "zoom_query": "each lug nut",
        "context": "A car wheel being changed.",
    },
    "pc": {
        "prompt": "Desktop computer tower lying on its side on a desk with the side panel removed, "
        "the motherboard, the RAM sticks and a large graphics card clearly visible.",
        "query": "the graphics card and each RAM stick",
        "inventory": "the graphics card, each RAM stick, the CPU cooler, the motherboard, "
        "the power supply and each case fan",
        "context": "A desktop computer being upgraded.",
    },
    "phone": {
        "prompt": "Top-down close photo of an opened smartphone lying on a grey anti-static mat, "
        "the back glass removed and set beside it. The large flat black battery fills the lower "
        "half. A small metal bracket covers the battery connector near the top of the battery and "
        "is held by four tiny silver Phillips screws, clearly visible. Nothing loose lies on the "
        "battery. A plastic spudger and a precision screwdriver lie beside the phone.",
        "query": "the battery and the metal bracket over the battery connector",
        "zoom_into": "bracket",
        "zoom_query": "each tiny screw head on this metal bracket",
        "context": "An opened smartphone during a battery replacement.",
    },
    "drill": {
        "prompt": "Cordless drill lying on a workbench, its keyless chuck open and in focus, a few "
        "drill bits lined up beside it.",
        "query": "the drill chuck",
        "context": "A cordless drill whose chuck is being replaced.",
    },
    "coffee": {
        "prompt": "Espresso machine on a kitchen counter with its water tank lifted out and set "
        "beside it, a descaling bottle next to it.",
        "query": "the removed water tank and the portafilter",
        "context": "An espresso machine being descaled.",
    },
    "guitar": {
        "prompt": "Close view of an acoustic guitar headstock on a workbench with six tuning pegs "
        "and old strings, a string winder beside it.",
        "query": "each tuning peg",
        "context": "A guitar being restrung.",
    },
    "controller": {
        "prompt": "Opened game controller on an anti-static mat, the front shell removed, the "
        "circuit board with the two analog stick modules clearly visible, tiny screws beside it.",
        "query": "the two analog stick modules",
        "inventory": "each analog stick module, the circuit board, the controller shell, "
        "the ribbon cable and the tweezers",
        "context": "A game controller with stick drift being repaired.",
    },
    "shelf": {
        "prompt": "Flat-pack bookshelf side panel lying on a living room floor, round metal cam "
        "locks set in their holes along the edge, wooden dowels and an Allen key next to it.",
        "query": "each metal cam bolt standing up from the panel",
        "context": "A flat-pack bookshelf being assembled.",
    },
    "lamp": {
        "prompt": "Desk lamp on a desk with the bulb removed and lying beside it, the empty bulb "
        "socket clearly visible inside the shade.",
        "query": "the lamp shade",
        "zoom_into": "shade",
        "zoom_query": "the empty brass bulb socket inside the shade",
        "context": "A desk lamp whose socket is being checked.",
    },
    "aircon": {
        "prompt": "Outdoor unit of a split air conditioner on a wall bracket, the copper "
        "refrigerant lines and their service valves visible at the side.",
        "query": "each refrigerant service valve and the copper refrigerant lines",
        "context": "An air conditioner refrigerant circuit: a job for a certified technician only.",
        "refused": "yes",
    },
    "vacuum": {
        "prompt": "Robot vacuum cleaner turned upside down on a wooden floor, its round body seen "
        "from below: the main roller brush, the two side brushes and the two drive wheels clearly "
        "visible, a small screwdriver beside it.",
        "query": "the main roller brush and each side brush",
        "context": "A robot vacuum whose brushes are being replaced.",
    },
    "boiler": {
        "prompt": "Wall-mounted gas boiler in a utility room with its front cover removed, "
        "showing the burner, the gas valve and pipes.",
        "query": "the gas valve and the burner",
        "context": "A gas boiler: a job for a registered gas engineer only.",
        "refused": "yes",
    },
    "table": {
        "prompt": "Flat-pack side table being assembled on a rug, the tabletop upside down with "
        "its four legs lying beside it and the bolts and Allen key in a small dish.",
        "query": "the tabletop and each wooden table leg",
        "min_fill": "0.05",
        "context": "A side table being assembled.",
    },
}


def outline(mask: np.ndarray) -> list[list[int]]:
    """The largest outer contour of a mask, simplified, on the 0..1000 grid."""
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []
    biggest = max(contours, key=cv2.contourArea)
    simple = cv2.approxPolyDP(biggest, 0.004 * cv2.arcLength(biggest, True), True)
    height, width = mask.shape[:2]
    return [[round(x * 1000 / width), round(y * 1000 / height)] for x, y in simple[:, 0, :]]


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
        side = min(max(x2 - x1, y2 - y1, 0.02 * min(width, height)) * 3, max(width, height) * 1.4)
        cx, cy = (x1 + x2) / 2 + pad, (y1 + y2) / 2 + pad
        left, top = max(0, int(cx - side / 2)), max(0, int(cy - side / 2))
        crop = padded[top : top + int(side), left : left + int(side)]
        scale = TILE / crop.shape[1]
        tile = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_CUBIC)
        corner1 = (int((x1 + pad - left) * scale) - 3, int((y1 + pad - top) * scale) - 3)
        corner2 = (int((x2 + pad - left) * scale) + 3, int((y2 + pad - top) * scale) + 3)
        cv2.rectangle(tile, corner1, corner2, (0, 220, 0), 2)
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
    client: MetaClient, model: str, image: np.ndarray, marks: list[dict], context: str
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


def cut(
    client: MetaClient,
    image_path: Path,
    query: str,
    context: str,
    frame: list[int],
    max_boxes: int = 8,
    min_fill: float = MIN_FILL,
) -> tuple[list[dict], list[dict]]:
    """Ground ``query`` in ``image_path`` and cut each box out with SAM.

    ``image_path`` shows the ``frame`` region (0..1000 grid) of the photo, so every box and
    outline is mapped back to the whole photo. Returns the kept marks and the dropped ones.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise MetaError(f"unreadable image: {image_path}")
    height, width = image.shape[:2]
    fx, fy = frame[0], frame[1]
    sx, sy = (frame[2] - frame[0]) / 1000, (frame[3] - frame[1]) / 1000

    def back(box: list[int] | tuple[int, ...]) -> list[int]:
        x1, y1, x2, y2 = box
        return [round(fx + x1 * sx), round(fy + y1 * sy), round(fx + x2 * sx), round(fy + y2 * sy)]

    marks: list[dict] = []
    dropped: list[dict] = []
    boxes = client.ground(image_path, query, context=context, max_boxes=max_boxes)
    if not boxes:
        return marks, dropped
    detections, sent = client.segment_boxes(image_path, [b.box for b in boxes])
    by_index = {int(d.object_id) - 1: d for d in detections if d.object_id.isdigit()}
    for index, ground_box in enumerate(boxes):
        detection = by_index.get(index)
        mask = full_mask(detection, sent, image.shape) if detection else None
        if detection is None or mask is None or not mask.any():
            dropped.append(
                {"label": ground_box.label, "box": back(ground_box.box), "why": "no mask"}
            )
            continue
        x1, y1, x2, y2 = ground_box.box
        fill = float(mask.sum()) / (max(1, (x2 - x1) * (y2 - y1)) * width * height / 1e6)
        confidence = round(detection.confidence or 0, 2)
        if confidence < MIN_CONFIDENCE or fill < min_fill:
            why = f"weak cut-out: confidence {confidence}, fill {fill:.2f}"
            dropped.append({"label": ground_box.label, "box": back(ground_box.box), "why": why})
            continue
        points = [[round(fx + x * sx), round(fy + y * sy)] for x, y in outline(mask)]
        xs, ys = [x for x, _ in points], [y for _, y in points]
        marks.append(
            {
                "label": ground_box.label,
                "box": back(ground_box.box),
                "cut_box": [min(xs), min(ys), max(xs), max(ys)],
                "outline": points,
                "confidence": confidence,
            }
        )
    return marks, dropped


def zoom(photo: Path, region: list[int], target: Path) -> list[int]:
    """Save ``region`` (0..1000 grid, padded by a quarter) enlarged to ``target``; return it."""
    image = cv2.imread(str(photo))
    height, width = image.shape[:2]
    x1, y1, x2, y2 = region
    pad_x, pad_y = (x2 - x1) // 4, (y2 - y1) // 4
    frame = [max(0, x1 - pad_x), max(0, y1 - pad_y), min(1000, x2 + pad_x), min(1000, y2 + pad_y)]
    crop = image[
        frame[1] * height // 1000 : frame[3] * height // 1000,
        frame[0] * width // 1000 : frame[2] * width // 1000,
    ]
    scale = 1280 / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(target), crop)
    return frame


def overlap(a: list[int], b: list[int]) -> float:
    """Intersection over the smaller box, for removing the same part found twice."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / max(1, smaller)


def refine(
    client: MetaClient, photo: Path, marks: list[dict], dropped: list[dict], context: str
) -> tuple[list[dict], list[dict]]:
    """Find every small part again on a close-up around it, where its position is exact."""
    small = [
        m
        for m in marks + dropped
        if not m.get("zoom")
        and max(m["box"][2] - m["box"][0], m["box"][3] - m["box"][1]) < SMALL_PART
    ]
    if not small:
        return marks, dropped
    kept = [m for m in marks if m not in small]
    lost = [m for m in dropped if m not in small]
    with tempfile.TemporaryDirectory() as tmp:
        for n, mark in enumerate(small):
            x1, y1, x2, y2 = mark["box"]
            cx, cy, half = (x1 + x2) // 2, (y1 + y2) // 2, max(70, (x2 - x1) * 3, (y2 - y1) * 3)
            region = [
                max(0, cx - half),
                max(0, cy - half),
                min(1000, cx + half),
                min(1000, cy + half),
            ]
            target = Path(tmp) / f"part{n}.png"
            frame = zoom(photo, region, target)
            query = f"the single {mark['label']} closest to the centre of this close-up"
            found, missed = cut(client, target, query, context, frame, max_boxes=1)
            for item in found:
                item["zoom"] = True
                if all(overlap(item["cut_box"], other["cut_box"]) < 0.3 for other in kept):
                    kept.append(item)
            lost += missed
    return kept, lost


def make(client: MetaClient, model: str, name: str, subject: dict[str, str], fresh: bool) -> dict:
    """Draw, ground, segment and check one subject; write its photo and marks."""
    photo = OUT / f"{name}.webp"
    if fresh or not photo.exists():
        photo.write_bytes(client.generate_image(STYLE + " " + subject["prompt"], size="1024x1024"))
    image = cv2.imread(str(photo))
    if image is None:
        raise MetaError(f"unreadable photo: {photo}")
    height, width = image.shape[:2]
    marks: list[dict] = []
    dropped: list[dict] = []
    if subject["query"]:
        min_fill = float(subject.get("min_fill", MIN_FILL))
        marks, dropped = cut(
            client, photo, subject["query"], subject["context"], [0, 0, 1000, 1000], 8, min_fill
        )
        parent = subject.get("zoom_into", "")
        holder = next((m for m in marks if parent and parent in m["label"].lower()), None)
        if holder is not None:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "zoom.png"
                frame = zoom(photo, holder["cut_box"], target)
                small, lost = cut(client, target, subject["zoom_query"], subject["context"], frame)
            for mark in small:
                mark["zoom"] = True
            marks, dropped = marks + small, dropped + lost
        marks, dropped = refine(client, photo, marks, dropped, subject["context"])
        checked = confirm(client, model, image, marks, subject["context"])
        dropped += [mark for mark in checked if not mark["checked"]]
        marks = [mark for mark in checked if mark["checked"]]
    data = {
        "name": name,
        "width": width,
        "height": height,
        "query": subject["query"],
        "refused": subject.get("refused") == "yes",
        "dropped": dropped,
        "marks": marks,
    }
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def inventory(client: MetaClient, model: str, name: str, subject: dict[str, str]) -> list[dict]:
    """Every distinct part Spark can name on the photo, cut out by SAM and checked again.

    Stored as ``inventory`` next to the job's marks, so the page can show how much it sees.
    """
    photo = OUT / f"{name}.webp"
    image = cv2.imread(str(photo))
    if image is None:
        raise MetaError(f"unreadable photo: {photo}")
    query = subject.get(
        "inventory",
        "every distinct part of the object being repaired that you can clearly see, "
        "one box per part, each labelled with its own short specific name",
    )
    found, _ = cut(client, photo, query, subject["context"], [0, 0, 1000, 1000], 12, 0.1)
    checked = confirm(client, model, image, found, subject["context"])
    parts = [m for m in checked if m["checked"]]
    path = OUT / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["inventory"] = parts
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return parts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=list(SUBJECTS))
    parser.add_argument("--cap", type=float, default=2.0)
    parser.add_argument("--fresh", action="store_true", help="draw the photo again")
    parser.add_argument("--inventory", action="store_true", help="name every part on the photo")
    args = parser.parse_args()
    settings = dataclasses.replace(get_settings(), job_budget_usd=args.cap)
    if not settings.model_api_key:
        print("MODEL_API_KEY is not set", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    client = MetaClient(settings, job_dir=settings.data_dir / "web_photos")
    for name in args.only:
        try:
            if args.inventory:
                parts = inventory(client, settings.spark_model, name, SUBJECTS[name])
                print(f"{name}: {len(parts)} parts named")
                print(f"spent so far: ${client.job_spend.total():.3f} of ${args.cap:.2f}")
                continue
            data = make(client, settings.spark_model, name, SUBJECTS[name], args.fresh)
            print(f"{name}: {len(data['marks'])} marks kept, {len(data['dropped'])} dropped")
        except BudgetExceeded as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            break
        except MetaError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
        print(f"spent so far: ${client.job_spend.total():.3f} of ${args.cap:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
