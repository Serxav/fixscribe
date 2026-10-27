"""Build a demo job with the real pipeline but a fake Meta client (costs nothing).

Usage: .venv/bin/python scripts/demo_job.py
Prints the job id; open http://localhost:8000/guides/<id> to see the guide.
Useful to work on the web pages without spending credits.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.config import get_settings
from app.jobs import create_job
from app.meta_client import set_client_factory
from app.pipeline.runner import run_job

SECONDS = 36

TURNS = [
    (1.0, "Step one, remove the two pentalobe screws at the bottom"),
    (7.0, "Step two, open the screen with the suction cup"),
    (13.0, "Paso tres, quita la tapa del conector de la batería"),
    (19.0, "Step four, disconnect the battery"),
    (25.0, "Step five, peel the adhesive strips and lift the battery"),
]


def step(
    title, instruction, start, end, action, removes, screws=0, warnings=(), conf=0.9, target=None
):
    return {
        "title": title,
        "instruction": instruction,
        "start_s": start,
        "end_s": end,
        "target_part": target or (removes[0] if removes else ""),
        "action": action,
        "removes": list(removes),
        "screw_count": screws,
        "warnings": list(warnings),
        "evidence": [{"t_s": (start + end) / 2, "source": "video", "text": title}],
        "confidence": conf,
    }


ANALYSIS = {
    "title": "Replace the battery",
    "device": "iPhone 12",
    "summary": "Open the phone from the bottom edge, disconnect the battery and lift it out.",
    "difficulty": "medium",
    "estimated_minutes": 25,
    "tools": ["P2 pentalobe", "Tri-point Y000", "Suction cup", "Opening pick", "Spudger"],
    "parts": ["display", "battery connector bracket", "battery"],
    "warnings": [
        "Discharge the battery below 25 % before you start: "
        "a charged lithium battery can catch fire if punctured."
    ],
    "steps": [
        step(
            "Remove the bottom screws",
            "Remove the two pentalobe screws next to the charging port.",
            1.0,
            7.0,
            "unscrew",
            ["bottom screws"],
            screws=2,
            target="phone body",
        ),
        step(
            "Open the screen",
            "Lift the screen with the suction cup and slide a pick along the edge.",
            7.0,
            13.0,
            "pry",
            ["display"],
            warnings=[
                "Do not insert the pick deeper than 3 mm: the display cables are close to the edge."
            ],
        ),
        step(
            "Remove the connector bracket",
            "Unscrew the bracket over the battery connector and lift it off.",
            13.0,
            19.0,
            "unscrew",
            ["battery connector bracket"],
            screws=3,
        ),
        step(
            "Disconnect the battery",
            "Pry the battery connector straight up with a spudger.",
            19.0,
            25.0,
            "disconnect",
            ["battery connector"],
            warnings=["Use a plastic tool only: metal can short the battery."],
        ),
        step(
            "Lift out the battery",
            "Pull the adhesive strips slowly at a low angle, then lift the battery out.",
            25.0,
            35.0,
            "remove",
            ["battery"],
            warnings=["Never bend or puncture the battery."],
            conf=0.45,
        ),
    ],
}


IDENTITY = {
    "object_name": "smartphone",
    "category": "electronics",
    "brand": "",
    "model": "",
    "task": "repair",
    "problem": "battery replacement",
    "hazards": ["lithium_battery", "sharp_edges"],
    "skill": "intermediate",
    "language": "en",
    "evidence": ["offline demo answer"],
    "confidence": 0.5,
}


# --- A synthetic phone on a workbench, so the offline demo looks like a repair ---------------
# Each part has its own flat color; the fake SAM below finds parts and screws by that color,
# so perception, the screw ledger and the 3D views work on real pixels, offline and for free.
BENCH = "6e5a46"
PARTS = [  # (name, color, x, y, w, h, visible-when)
    ("body", "3b4048", 180, 200, 360, 800, "1"),
    ("board", "1e6b48", 196, 216, 328, 300, "1"),
    ("battery", "2a5fa8", 212, 540, 296, 380, "lt(t,32)"),
    ("battery connector", "d8b02a", 390, 500, 60, 28, "lt(t,23)"),
    ("battery connector", "d8b02a", 390, 450, 60, 28, "gte(t,23)"),
    ("battery connector bracket", "c06a2b", 360, 470, 130, 80, "lt(t,18.5)"),
    ("display", "101317", 196, 216, 328, 724, "lt(t,10)"),
]
SCREWS = [  # (x, y, visible-when): 2 at the bottom edge, 3 on the bracket
    (300, 960, "lt(t,5)"),
    (402, 960, "lt(t,5)"),
    (366, 476, "lt(t,17)"),
    (464, 476, "lt(t,17)"),
    (415, 528, "lt(t,17)"),
]
SCREW_COLOR = "dfe3e8"
SCREW_SIDE = 20


def scene_filter() -> str:
    boxes = [
        f"drawbox=x={x}:y={y}:w={w}:h={h}:color=0x{color}:t=fill:enable='{when}'"
        for _, color, x, y, w, h, when in PARTS
    ]
    boxes += [
        f"drawbox=x={x}:y={y}:w={SCREW_SIDE}:h={SCREW_SIDE}:color=0x{SCREW_COLOR}:t=fill"
        f":enable='{when}'"
        for x, y, when in SCREWS
    ]
    return ",".join(boxes)


def find_colored(image_path, concept, max_side=1280):
    """Offline stand-in for SAM: boxes of the pixels that have the concept's color."""
    import cv2

    from app.meta_client import Detection

    image = cv2.imread(str(image_path))
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, (int(width * scale), int(height * scale)))
    color = color_of(concept)
    if color is None:
        return [], (image.shape[1], image.shape[0])
    mask = color_mask(image, color)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    min_area = 0.00004 * image.shape[0] * image.shape[1]
    found = [
        Detection(f"o{i}", (float(x), float(y), float(x + w), float(y + h)), 0.9, None, None, None)
        for i, (x, y, w, h, area) in enumerate(stats[1:], start=1)
        if area >= max(min_area, 12)
    ]
    return found, (image.shape[1], image.shape[0])


def color_of(concept):
    """The flat color the synthetic scene uses for a concept, or None."""
    concept = concept.lower()
    if "screw" in concept and "bracket" not in concept:
        return SCREW_COLOR
    # Exact part name first, then the longest part name inside the concept, then the reverse.
    names = sorted({name for name, *_ in PARTS}, key=len, reverse=True)
    name = next((n for n in names if n == concept), None)
    name = name or next((n for n in names if n in concept), None)
    name = name or next((n for n in names if concept in n), None)
    return next(c for n, c, *_ in PARTS if n == name) if name else None


def color_mask(image, color):
    import numpy as np

    rgb = [int(color[i : i + 2], 16) for i in (0, 2, 4)]
    target = np.array(rgb[::-1], dtype=np.int16)  # BGR
    return (np.abs(image.astype(np.int16) - target).max(axis=2) < 28).astype(np.uint8)


def palette_color_at(image, box):
    """The scene color (part or screw) that covers most of the box (majority of pixels)."""
    left, top, right, bottom = (int(v) for v in box)
    region = image[max(0, top) : bottom, max(0, left) : right]
    colors = [c for _, c, *_ in PARTS] + [SCREW_COLOR]
    return max(colors, key=lambda c: int(color_mask(region, c).sum()) if region.size else 0)


def track_colored(video_path, concept=None, boxes=(), size=None):
    """Offline stand-in for SAM video tracking.

    With a concept: every component of the concept's color, with stable ids. With box prompts:
    only the prompted objects, each followed from its box (nearest component of its color).
    """
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    images = []
    while True:
        ok, image = capture.read()
        if not ok:
            break
        images.append(image)
    capture.release()
    if not images:
        return []
    height, width = images[0].shape[:2]
    if boxes:
        seeds = []
        for object_id, frame, box in boxes:
            color = palette_color_at(images[min(frame, len(images) - 1)], box)
            seeds.append((object_id, color, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)))
    else:
        color = color_of(concept)
        seeds = [(None, color, None)] if color else []
    tracks, previous, next_id = [], {}, 1
    for index, image in enumerate(images):
        objects, current, claimed = [], {}, set()
        for seed_id, color, start in seeds:
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(
                color_mask(image, color)
            )
            for label in range(1, count):
                x, y, w, h, area = stats[label]
                if area < max(12, 0.00004 * width * height):
                    continue
                cx, cy = centroids[label]
                if seed_id is not None:  # follow only the prompted object
                    px, py = previous.get(seed_id, start)
                    if abs(px - cx) + abs(py - cy) > 60:
                        continue
                    object_id = seed_id
                else:
                    near = [
                        o for o, (px, py) in previous.items() if abs(px - cx) + abs(py - cy) < 40
                    ]
                    object_id = near[0] if near else next_id
                    next_id += 0 if near else 1
                if object_id in current or (color, label) in claimed:
                    continue
                claimed.add((color, label))
                current[object_id] = (cx, cy)
                objects.append(
                    SimpleNamespace(
                        object_id=object_id,
                        box=(float(x), float(y), float(x + w), float(y + h)),
                        confidence=0.9,
                        mask=labels == label,
                        svg_path=None,
                    )
                )
        previous = {**previous, **current} if seeds and seeds[0][0] is not None else current
        if objects:
            frame = SimpleNamespace(frame=index, width=width, height=height, objects=objects)
            tracks.append(frame)
    return tracks


NARRATION = {
    "intro": "Today we replace the battery of a smartphone. You need a pentalobe and a tri-point"
    " screwdriver, a suction cup and a plastic pick.",
    "outro_disassemble": "The old battery is out. Great work.",
    "outro_assemble": "Everything is back in place. Your phone is ready.",
    "steps": [
        {
            "index": 1,
            "disassemble": "Remove the two pentalobe screws next to the charging port.",
            "assemble": "Drive the two pentalobe screws back in next to the charging port.",
        },
        {
            "index": 2,
            "disassemble": "Lift the screen with the suction cup. Do not push the pick"
            " deeper than three millimetres.",
            "assemble": "Lay the screen back and press the edges until it clicks.",
        },
        {
            "index": 3,
            "disassemble": "Unscrew the three screws of the connector bracket and lift it off.",
            "assemble": "Put the bracket back and drive in the three screws.",
        },
        {
            "index": 4,
            "disassemble": "Pry the battery connector straight up with a plastic tool.",
            "assemble": "Press the battery connector down until it snaps in.",
        },
        {
            "index": 5,
            "disassemble": "Pull the adhesive strips slowly and lift the battery out.",
            "assemble": "Place the new battery and press it gently onto the adhesive.",
        },
    ],
}


class FakeMeta:
    def __init__(self, settings, **kwargs):
        pass

    def transcribe(self, wav, **kwargs):
        turns = [
            {
                "turnId": i,
                "startMs": int(t * 1000),
                "endMs": int(t * 1000) + 2500,
                "transcript": text,
            }
            for i, (t, text) in enumerate(TURNS)
        ]
        return {
            "sessionId": "demo",
            "transcript": "",
            "audioDurationMs": SECONDS * 1000,
            "turns": turns,
        }

    def upload_file(self, path):
        return "file-demo"

    def respond(self, **kwargs):
        # Pass 2 answers "not sure" (confidence 0), so the plan keeps the first analysis.
        unsure = {"start_s": 0, "end_s": 0, "instruction": "", "action": "other", "removes": []}
        unsure |= {"screw_count": 0, "warnings": [], "confidence": 0}
        answers = {
            "repair_analysis": ANALYSIS,
            "repair_identity": IDENTITY,
            "refined_step": unsure,
            "film_narration": NARRATION,
        }
        name = kwargs["text"]["format"]["name"]
        if name not in answers:
            raise RuntimeError(f"the offline demo has no answer for {name}")
        return SimpleNamespace(output_text=json.dumps(answers[name]))

    def delete_file(self, file_id):
        pass

    def segment(self, image_path, concept, max_side=1280):
        return find_colored(image_path, concept, max_side)

    def segment_video(self, video_path, concept=None, boxes=(), size=None, max_frames=600):
        return track_colored(video_path, concept, boxes, size)


def main() -> int:
    settings = get_settings()
    jobs_dir = settings.jobs_dir
    job_id = create_job(jobs_dir).job_id
    original = Path(jobs_dir / job_id / "original.mp4")
    # A moving test pattern with a tone: portrait, like a phone video.
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=0x{BENCH}:size=720x1280:rate=30:duration={SECONDS}",
            "-f", "lavfi", "-i", f"sine=frequency=330:duration={SECONDS}",
            "-vf", scene_filter(),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(original),
        ],
        check=True,
    )  # fmt: skip
    set_client_factory(FakeMeta)  # one switch: no stage can reach the real Meta API
    status = run_job(job_id, settings, jobs_dir=jobs_dir)
    print(f"job {job_id}: {status.state} {status.error or ''}".rstrip())
    if status.state == "done":
        # The home page shows this guide as the example.
        (settings.data_dir / "example_job.txt").write_text(job_id)
    print(f"open http://localhost:8000/guides/{job_id}")
    return 0 if status.state == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
