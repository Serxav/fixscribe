"""The agent's tools. Each one checks the agent's proof before it changes the case record.

The checks live here, outside the model: a part only enters the catalog when SAM 3.1 cuts it out
inside the box the agent gave, a step only enters the guide when its parts are proven, its times
fit the video and its quote is really in the narration. A refusal goes back to the model with the
reason, so it can try again; it never crashes the run.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.agent.record import AgentRecord, AgentStep, Box, Part, Question, agent_dir
from app.meta_client import BudgetExceeded, Detection, MetaError
from app.pipeline.motion import cutout
from app.schemas import ACTIONS

MAX_ASKS = 3
MIN_MASK_FILL = 0.10  # SAM must fill at least this share of the box, or the box missed the part
MIN_CONFIDENCE = 0.30
QUOTE_WINDOW_S = 8.0  # the quote must be said near the step


@dataclass
class Result:
    ok: bool
    text: str
    image: str = ""  # relative to agent/, shown to the model and in the console
    stop: bool = False  # the run waits for the person after this tool


@dataclass
class Case:
    """Everything a tool needs: the job, the Meta client and the record it may change."""

    job_dir: Path
    client: Any
    record: AgentRecord
    duration_s: float
    turns: list[tuple[float, float, str]] = field(default_factory=list)  # narration
    asks: int = 0

    @property
    def video(self) -> Path:
        return self.job_dir / "video.mp4"

    def path(self, relative: str) -> Path:
        return agent_dir(self.job_dir) / relative


def valid_box(value: Any) -> Box | None:
    """A 0..1000 box [x_min, y_min, x_max, y_max] at least 4 units wide and tall, else None."""
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    if not all(isinstance(v, int | float) for v in value):
        return None
    x1, y1, x2, y2 = (int(min(1000, max(0, v))) for v in value)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return (x1, y1, x2, y2)


def frame_time(relative: str) -> float | None:
    """The second a frame was taken at, from its name ("frames/t12.4.jpg" -> 12.4)."""
    match = re.fullmatch(r"frames/t(\d+(?:\.\d+)?)\.jpg", relative)
    return float(match.group(1)) if match else None


def normalize(text: str) -> str:
    """Lower case, no accents, no punctuation, single spaces: for matching quotes."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def full_mask(detection: Detection, size_sent: tuple[int, int], shape: tuple[int, ...]) -> Any:
    """SAM's box-local mask placed on a full frame of ``shape`` (bool array), or None."""
    if detection.mask is None or detection.mask_size is None:
        return None
    mask_w, mask_h = detection.mask_size
    if mask_w <= 0 or mask_h <= 0 or len(detection.mask) < mask_w * mask_h:
        return None
    sent_w, sent_h = size_sent
    height, width = shape[:2]
    bounds = detection.mask_bounds or detection.box
    x1 = int(round(bounds[0] * width / sent_w))
    y1 = int(round(bounds[1] * height / sent_h))
    x2 = max(x1 + 1, min(width, int(round(bounds[2] * width / sent_w))))
    y2 = max(y1 + 1, min(height, int(round(bounds[3] * height / sent_h))))
    local = np.frombuffer(detection.mask[: mask_w * mask_h], dtype=np.uint8).reshape(mask_h, mask_w)
    scaled = cv2.resize(local, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
    full = np.zeros((height, width), dtype=bool)
    full[y1:y2, x1:x2] = scaled > 0
    return full


def draw_boxes(image: Any, boxes: list[Box]) -> Any:
    """A copy with numbered boxes, so the model can see what it pointed at."""
    result = image.copy()
    height, width = result.shape[:2]
    for number, (x1, y1, x2, y2) in enumerate(boxes, start=1):
        p1 = (x1 * width // 1000, y1 * height // 1000)
        p2 = (x2 * width // 1000, y2 * height // 1000)
        cv2.rectangle(result, p1, p2, (255, 113, 0), 3)
        cv2.putText(result, str(number), (p1[0] + 6, p1[1] + 30), 0, 1.0, (255, 113, 0), 3)
    return result


# --- the tools --------------------------------------------------------------------------------


def look(case: Case, t_s: float) -> Result:
    """Save the frame at second ``t_s`` and show it to the model."""
    if not 0 <= t_s <= case.duration_s:
        return Result(False, f"t_s must be between 0 and {case.duration_s:.1f}")
    relative = f"frames/t{t_s:.1f}.jpg"
    target = case.path(relative)
    if not target.exists():
        capture = cv2.VideoCapture(str(case.video))
        capture.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            return Result(False, f"could not read the video at {t_s:.1f} s")
        target.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(target), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return Result(True, f"frame {relative} (the image follows)", image=relative)


def point(case: Case, frame: str, query: str) -> Result:
    """Ask Muse Spark where ``query`` is on a frame the agent looked at; boxes on 0..1000."""
    if frame_time(frame) is None or not case.path(frame).exists():
        return Result(False, f"unknown frame {frame!r}: call look first")
    if not query.strip():
        return Result(False, "query must describe the object")
    context = f"{case.record.objective}"
    try:
        found = case.client.ground(case.path(frame), query, context=context, max_boxes=6)
    except BudgetExceeded:
        raise
    except MetaError as exc:
        return Result(False, f"pointing failed: {exc}")
    if not found:
        return Result(True, "not visible on this frame: try another second")
    image = cv2.imread(str(case.path(frame)))
    relative = frame.replace(".jpg", "_points.jpg")
    cv2.imwrite(str(case.path(relative)), draw_boxes(image, [g.box for g in found]))
    lines = [f"{n}: {list(g.box)} {g.label} ({g.why})" for n, g in enumerate(found, start=1)]
    return Result(True, "boxes on frame " + frame + ":\n" + "\n".join(lines), image=relative)


def add_part(case: Case, id: str, name: str, count: int, frame: str, box: list[int]) -> Result:
    """Add part ``id`` to the catalog once SAM cuts it out inside ``box`` on ``frame``."""
    if not re.fullmatch(r"[A-Z]", id):
        return Result(False, "id must be one capital letter, A to Z")
    if not 1 <= len(name.strip()) <= 40 or not 1 <= count <= 50:
        return Result(False, "name must be 1-40 characters and count 1-50")
    t_s = frame_time(frame)
    if t_s is None or not case.path(frame).exists():
        return Result(False, f"unknown frame {frame!r}: call look first")
    clean = valid_box(box)
    if clean is None:
        return Result(False, "box must be [x_min, y_min, x_max, y_max] on 0..1000, at least 4 wide")
    image = cv2.imread(str(case.path(frame)))
    try:
        detections, size_sent = case.client.segment_boxes(case.path(frame), [clean])
    except BudgetExceeded:
        raise
    except MetaError as exc:
        return Result(False, f"SAM could not run: {exc}")
    mask = full_mask(detections[0], size_sent, image.shape) if detections else None
    if mask is None or not mask.any():
        return Result(
            False, "SAM found nothing inside that box: pick a clearer frame or a tighter box"
        )
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (
        clean[0] * width // 1000,
        clean[1] * height // 1000,
        clean[2] * width // 1000,
        clean[3] * height // 1000,
    )
    fill = float(mask[y1:y2, x1:x2].sum()) / max(1, (x2 - x1) * (y2 - y1))
    confidence = detections[0].confidence
    if fill < MIN_MASK_FILL:
        return Result(
            False, f"SAM's cut-out fills only {fill:.0%} of the box: the box is too loose"
        )
    if confidence is not None and confidence < MIN_CONFIDENCE:
        return Result(False, f"SAM is unsure ({confidence:.2f}): try a frame where it is clearer")
    crop = f"crops/{id}.png"
    case.path(crop).parent.mkdir(parents=True, exist_ok=True)
    cutout(image, mask, case.path(crop))
    evidence = [f"SAM 3.1 cut it out on {frame} ({fill:.0%} of the box)"]
    if confidence is not None:
        evidence.append(f"SAM confidence {confidence:.2f}")
    part = Part(
        id=id,
        name=name.strip(),
        count=count,
        frame=frame,
        t_s=t_s,
        box=clean,
        crop=crop,
        verified=True,
        evidence=evidence,
    )
    case.record.parts = [p for p in case.record.parts if p.id != id] + [part]
    case.record.parts.sort(key=lambda p: p.id)
    return Result(True, f"part {id} ({name}) x{count} added: " + "; ".join(evidence), image=crop)


def quote_found(case: Case, quote: str, start_s: float, end_s: float) -> bool:
    """True when ``quote`` was said near the step (accents, case and punctuation ignored)."""
    wanted = normalize(quote)
    near = [
        text
        for a, b, text in case.turns
        if b >= start_s - QUOTE_WINDOW_S and a <= end_s + QUOTE_WINDOW_S
    ]
    return bool(wanted) and wanted in normalize(" ".join(near))


def add_step(
    case: Case,
    n: int,
    action: str,
    text: str,
    parts: list[str],
    start_s: float,
    end_s: float,
    frame: str,
    to_box: list[int],
    quote: str,
) -> Result:
    """Add (or replace) step ``n`` once its parts, times, frame and quote check out."""
    problems = []
    if n < 1:
        problems.append("n starts at 1")
    if action not in ACTIONS:
        problems.append(f"action must be one of: {', '.join(ACTIONS)}")
    if not 3 <= len(text.strip()) <= 300:
        problems.append("text must be 3-300 characters")
    known = {p.id: p for p in case.record.parts}
    missing = [p for p in parts if p not in known]
    if not parts or missing:
        problems.append(f"parts must be catalog letters; unknown: {missing or 'none given'}")
    if not 0 <= start_s < end_s <= case.duration_s + 0.5:
        problems.append(f"need 0 <= start_s < end_s <= {case.duration_s:.1f}")
    t_s = frame_time(frame)
    if t_s is None or not case.path(frame).exists():
        problems.append(f"unknown frame {frame!r}: look at the end of the step first")
    elif not start_s - 1 <= t_s <= end_s + 3:
        problems.append(f"frame {frame} is not inside the step ({start_s:.1f}-{end_s:.1f} s)")
    clean = valid_box(to_box)
    if clean is None:
        problems.append("to_box must be [x_min, y_min, x_max, y_max] on 0..1000 (use point)")
    if case.turns and not quote.strip():
        problems.append("copy the person's own words for this step into quote")
    elif quote.strip() and not quote_found(case, quote, start_s, end_s):
        problems.append("quote is not in the narration near this step: copy it exactly")
    if problems:
        return Result(False, "step refused: " + "; ".join(problems))
    evidence = [f"parts {', '.join(parts)} proven by SAM", f"result seen on {frame}"]
    if quote.strip():
        evidence.append("quote found in the narration")
    step = AgentStep(
        n=n,
        action=action,
        text=text.strip(),
        parts=parts,
        start_s=start_s,
        end_s=end_s,
        frame=frame,
        to_box=clean,
        quote=quote.strip(),
        verified=True,
        evidence=evidence,
    )
    case.record.steps = [s for s in case.record.steps if s.n != n] + [step]
    case.record.steps.sort(key=lambda s: s.n)
    return Result(True, f"step {n} added: " + "; ".join(evidence))


def ask_person(case: Case, text: str, frame: str, box: list[int], options: list[str]) -> Result:
    """Stop and ask the person one short question about a frame."""
    if case.asks >= MAX_ASKS:
        return Result(False, f"you already asked {MAX_ASKS} times: decide from the video")
    if not 3 <= len(text.strip()) <= 200 or len(options) > 4:
        return Result(False, "question must be 3-200 characters with at most 4 options")
    if frame and not case.path(frame).exists():
        return Result(False, f"unknown frame {frame!r}")
    case.asks += 1
    case.record.question = Question(
        text=text.strip(),
        frame=frame,
        box=valid_box(box),
        options=[o.strip() for o in options if o.strip()],
    )
    case.record.status = "needs_input"
    return Result(True, "question sent: waiting for the person", stop=True)


def submit_guide(case: Case) -> Result:
    """File the guide for the person's sign-off, if the record is complete."""
    record = case.record
    problems = []
    numbers = [s.n for s in record.steps]
    if not numbers:
        problems.append("there are no steps")
    elif numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"steps must be numbered 1..N without gaps, got {numbers}")
    used = {p for s in record.steps for p in s.parts}
    unused = [p.id for p in record.parts if p.id not in used]
    if unused:
        problems.append(f"parts never used in a step: {', '.join(unused)}")
    times = [(s.start_s, s.n) for s in record.steps]
    if times != sorted(times):
        problems.append("steps must follow the video's time order")
    if problems:
        return Result(False, "guide refused: " + "; ".join(problems))
    record.question = None
    record.status = "awaiting_signoff"
    return Result(True, "guide filed: waiting for the person's sign-off", stop=True)


# --- definitions sent to the model (flat Responses API format, strict) -------------------------

_BOX = {
    "type": "array",
    "items": {"type": "integer"},
    "description": "[x_min, y_min, x_max, y_max] on 0..1000",
}


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


DEFINITIONS = [
    _tool("look", "Save the video frame at a second and see it.", {"t_s": {"type": "number"}}),
    _tool(
        "point",
        "Muse Spark finds an object on a frame you looked at and returns numbered boxes.",
        {"frame": {"type": "string"}, "query": {"type": "string"}},
    ),
    _tool(
        "add_part",
        "Add a part to the catalog. SAM 3.1 must cut it out inside the box, or it is refused.",
        {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "frame": {"type": "string"},
            "box": _BOX,
        },
    ),
    _tool(
        "add_step",
        "Add or replace step n. Checked: parts proven, times, frame inside the step, quote said.",
        {
            "n": {"type": "integer"},
            "action": {"type": "string", "enum": ACTIONS},
            "text": {"type": "string"},
            "parts": {"type": "array", "items": {"type": "string"}},
            "start_s": {"type": "number"},
            "end_s": {"type": "number"},
            "frame": {"type": "string"},
            "to_box": _BOX,
            "quote": {"type": "string"},
        },
    ),
    _tool(
        "ask_person",
        "Stop and ask the person one short question about a frame (max 3 per run).",
        {
            "text": {"type": "string"},
            "frame": {"type": "string"},
            "box": _BOX,
            "options": {"type": "array", "items": {"type": "string"}},
        },
    ),
    _tool("submit_guide", "File the finished guide for the person's sign-off.", {}),
]

_FUNCTIONS = {
    "look": look,
    "point": point,
    "add_part": add_part,
    "add_step": add_step,
    "ask_person": ask_person,
    "submit_guide": submit_guide,
}


def run_tool(case: Case, name: str, arguments: str) -> Result:
    """Run one tool call from the model. Bad names or arguments are refusals, never crashes."""
    function = _FUNCTIONS.get(name)
    if function is None:
        return Result(False, f"unknown tool {name!r}")
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        return function(case, **args)
    except BudgetExceeded:
        raise
    except (TypeError, ValueError) as exc:
        return Result(False, f"bad arguments for {name}: {exc}")
