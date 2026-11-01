"""Live mode: "where am I, what do I do now and which part is it?" from one camera frame.

While the user repairs, the phone sends a frame when the camera shows something new. Spark looks
at it next to the whole guide and the photos of the steps around the user and answers which step
this is, whether it looks right, what to do next and where the object is (``live_turn``, fast).
When the view holds still the parts are marked the way the landing photos were: close-up on the
object, Spark grounds and names the parts, SAM 3.1 cuts them and they show as "checking", then
Spark checks every cut-out and only the confirmed ones stay (``marks_stages``, slower). The calls
are capped and spend has its own counter in ``live/``, so a guide that used up its own budget
still gets a coach and a forgotten camera page cannot eat the budget.
"""

import io
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import cv2
import numpy as np
from PIL import Image, ImageOps
from pydantic import Field, ValidationError

from app import artifacts, spark
from app.agent.tools import full_mask
from app.artifacts import ArtifactError
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaError, make_client
from app.pipeline.verify import confirm
from app.schemas import Guide, Step, Strict, _object
from app.spark import SparkAnswerError

MAX_FRAME_BYTES = 4 * 1024**2
MAX_FRAME_SIDE = 1280
MAX_LIVE_CALLS_PER_JOB = 300
MAX_PARTS = 6
MIN_CONFIDENCE = 0.15  # same bar as the landing photos
MIN_FILL = 0.1
SMALL_PART = 50  # boxes narrower than this (0..1000 grid) get a margin: Spark is often half off
CROP_MARGIN = 0.2  # room around the object on the close-up
CLOSE_UP_SIDE = 1280
SURE = 0.8  # the next step is taken at once when Spark is this sure
GROUND_EFFORT = "low"  # pointing is the longest wait; the check keeps its full reasoning
MAX_SPILL = 0.25  # a cut-out with more than this outside its box ran over onto something else
SMOOTH = 0.012  # outline clean-up, as a share of the image's long side

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "live_v2.md"

PROFESSIONAL_LINE = "A qualified professional must do this repair."


class LiveError(Exception):
    """A user-facing reason the frame could not be answered."""


class LivePart(Strict):
    """One part named on the frame and cut out by SAM, on the frame's 0..1000 grid."""

    label: str
    target: bool = False  # the part this step works on
    box: list[int]
    outline: list[list[int]]
    confidence: float = Field(ge=0, le=1)


class LiveAnswer(Strict):
    """Which guide step the user is on, judged from one camera frame."""

    step: int = Field(ge=0)  # the step the coach stands on (0 = not started / not visible)
    seen: int = Field(default=0, ge=0)  # the step this one frame looks like
    pending: int = Field(default=0, ge=0)  # a different step waiting for a second frame to agree
    status: Literal["on_track", "wrong", "done_step", "unclear"]
    say: str  # one short sentence for the voice, in the guide language (<= 20 words)
    next: str  # the next action, imperative (<= 15 words)
    confidence: float = Field(ge=0, le=1)
    object_box: list[int] = []  # where the object is on the frame's 0..1000 grid, [] when unseen


LIVE_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "step": {"type": "integer"},
        "status": {
            "type": "string",
            "enum": ["on_track", "wrong", "done_step", "unclear"],
        },
        "say": {"type": "string"},
        "next": {"type": "string"},
        "confidence": {"type": "number"},
        "object_box": _object(
            {
                "visible": {"type": "boolean"},
                "x_min": {"type": "integer"},
                "y_min": {"type": "integer"},
                "x_max": {"type": "integer"},
                "y_max": {"type": "integer"},
            }
        ),
    }
)


def _describe_step(step: Step) -> str:
    """One prompt line per step: number, title, instruction, fasteners and the part it works on."""
    screws = step.screws
    if not screws or screws.count <= 0:
        fasteners = "none"
    else:
        kind = (screws.kind or "screw").strip() or "screw"
        fasteners = f"{screws.count} {kind}"
    part = (step.target_part or "").strip() or "none"
    return f"{step.index}. {step.title} — {step.instruction} — {fasteners} — part: {part}"


def nearby_steps(guide: Guide, last_step: int) -> list[Step]:
    """The step the user stands on and the next one: the two a new frame most likely shows."""
    first = max(last_step, 1)
    return [step for step in guide.steps if first <= step.index <= first + 1]


def build_prompt(guide: Guide, last_step: int = 0, photos: list[Step] | None = None) -> str:
    """Fill the live prompt template with the guide language, steps, last step and photos."""
    language = (guide.language or "").strip() or "en"
    steps_text = "\n".join(_describe_step(step) for step in guide.steps) or "(no steps)"
    listed = ", ".join(f"step {step.index}" for step in photos or []) or "none"
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("<<LANGUAGE>>", language)
    prompt = prompt.replace("<<STEPS>>", steps_text).replace("<<PHOTOS>>", listed)
    return prompt.replace("<<LAST_STEP>>", str(last_step))


def settle_step(last: int, pending: int, seen: int, confidence: float) -> tuple[int, int]:
    """One odd frame never moves the coach: returns (step to stand on, step still waiting).

    A different step needs two frames in a row, except the very first one and a sure next step.
    """
    if seen == 0 or seen == last:
        return last, 0
    if last == 0 or seen == pending or (seen == last + 1 and confidence >= SURE):
        return seen, 0
    return last, seen


def save_frame(job_dir: Path, frame: bytes, name: str = "frame.jpg") -> Path:
    """Phone frame bytes to an upright JPEG (max side 1280), written atomically."""
    if len(frame) > MAX_FRAME_BYTES:
        raise LiveError(f"frame is too big ({len(frame)} bytes, max {MAX_FRAME_BYTES} bytes)")
    if not frame:
        raise LiveError("frame is empty")
    try:
        with Image.open(io.BytesIO(frame)) as image:
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise LiveError(f"could not read the frame: {exc}") from exc
    upright.thumbnail((MAX_FRAME_SIDE, MAX_FRAME_SIDE), Image.Resampling.LANCZOS)
    dst = job_dir / "live" / name
    try:
        with artifacts.atomic_path(dst) as tmp:
            upright.save(tmp, format="JPEG", quality=85)
    except OSError as exc:
        raise LiveError(f"could not save the frame: {exc}") from exc
    return dst


def read_calls(job_dir: Path) -> int:
    """How many live Spark calls this job already made (0 when unknown)."""
    try:
        return max(0, int((job_dir / "live" / "calls.txt").read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return 0


def _polygon(mask: np.ndarray) -> list[list[int]]:
    """A mask's largest outer contour, simplified, on the 0..1000 grid."""
    raw = mask.astype(np.uint8)
    side = max(3, int(max(raw.shape[:2]) * SMOOTH) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
    smooth = cv2.morphologyEx(
        cv2.morphologyEx(raw, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel
    )
    # a part thinner than the clean-up would vanish: it keeps its raw outline
    contours, _ = cv2.findContours(
        smooth if smooth.any() else raw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []
    biggest = max(contours, key=cv2.contourArea)
    simple = cv2.approxPolyDP(biggest, 0.004 * cv2.arcLength(biggest, True), True)
    height, width = mask.shape[:2]
    return [[round(x * 1000 / width), round(y * 1000 / height)] for x, y in simple[:, 0, :]]


def object_region(raw: Any) -> list[int]:
    """Spark's object box, checked; [] when it did not see the object."""
    if not isinstance(raw, dict) or raw.get("visible") is not True:
        return []
    try:
        xs = sorted(max(0, min(1000, int(raw[key]))) for key in ("x_min", "x_max"))
        ys = sorted(max(0, min(1000, int(raw[key]))) for key in ("y_min", "y_max"))
    except (KeyError, TypeError, ValueError):
        return []
    if xs[1] - xs[0] < 20 or ys[1] - ys[0] < 20:
        return []
    return [xs[0], ys[0], xs[1], ys[1]]


def _padded(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """A small box with a margin; a big one stays as it is."""
    x1, y1, x2, y2 = box
    if max(x2 - x1, y2 - y1) >= SMALL_PART:
        return box
    mx, my = max(6, (x2 - x1) // 2), max(6, (y2 - y1) // 2)
    return (max(0, x1 - mx), max(0, y1 - my), min(1000, x2 + mx), min(1000, y2 + my))


def _coach_client(job_dir: Path, settings: Settings) -> Any:
    """A client that counts the coach's spend apart from the guide's."""
    coach = replace(settings, job_budget_usd=settings.live_budget_usd)
    return make_client(coach, job_dir=job_dir / "live")


def _count_call(job_dir: Path) -> int:
    """Refuse past the cap; returns the number of calls made so far."""
    calls = read_calls(job_dir)
    if calls >= MAX_LIVE_CALLS_PER_JOB:
        raise LiveError(f"live limit reached for this job ({MAX_LIVE_CALLS_PER_JOB} calls max)")
    return calls


def close_up(image: np.ndarray, region: list[int]) -> tuple[np.ndarray, list[int]]:
    """The object enlarged, and the part of the frame it shows on the 0..1000 grid."""
    x1, y1, x2, y2 = region or [0, 0, 1000, 1000]
    mx, my = int((x2 - x1) * CROP_MARGIN), int((y2 - y1) * CROP_MARGIN)
    frame = [max(0, x1 - mx), max(0, y1 - my), min(1000, x2 + mx), min(1000, y2 + my)]
    height, width = image.shape[:2]
    crop = image[
        frame[1] * height // 1000 : frame[3] * height // 1000,
        frame[0] * width // 1000 : frame[2] * width // 1000,
    ]
    scale = CLOSE_UP_SIDE / max(crop.shape[:2])
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC), frame


def _spill(mask: np.ndarray, box: Any) -> float:
    """The share of a cut-out outside its box (with a small margin), from 0 to 1."""
    height, width = mask.shape[:2]
    x1, y1, x2, y2 = _padded(tuple(box))
    mx, my = (x2 - x1) // 20, (y2 - y1) // 20
    inside = mask[
        max(0, y1 - my) * height // 1000 : min(1000, y2 + my) * height // 1000,
        max(0, x1 - mx) * width // 1000 : min(1000, x2 + mx) * width // 1000,
    ]
    return 1 - float(inside.sum()) / max(1.0, float(mask.sum()))


def cut_marks(client: Any, path: Path, image: np.ndarray, grounded: list[Any]) -> list[dict]:
    """SAM cuts every grounded box out of ``path``; weak cut-outs are dropped."""
    detections, sent = client.segment_boxes(path, [_padded(g.box) for g in grounded])
    by_index = {int(d.object_id) - 1: d for d in detections if str(d.object_id).isdigit()}
    height, width = image.shape[:2]
    marks = []
    for index, found in enumerate(grounded):
        detection = by_index.get(index)
        mask = full_mask(detection, sent, image.shape) if detection else None
        if detection is None or mask is None or not mask.any():
            continue
        x1, y1, x2, y2 = found.box
        if _spill(mask, found.box) > MAX_SPILL:
            continue
        fill = float(mask.sum()) / (max(1, (x2 - x1) * (y2 - y1)) * width * height / 1e6)
        confidence = round(min(1.0, detection.confidence or 0), 2)
        points = _polygon(mask)
        if confidence < MIN_CONFIDENCE or fill < MIN_FILL or len(points) < 3:
            continue
        xs, ys = [x for x, _ in points], [y for _, y in points]
        marks.append(
            {
                "label": found.label,
                "box": list(found.box),
                "cut_box": [min(xs), min(ys), max(xs), max(ys)],
                "outline": points,
                "confidence": confidence,
            }
        )
    return marks


def manual_parts(guide: Guide, step_index: int) -> list[str]:
    """The parts the manual has reached by this step: the only names the coach uses here."""
    last = step_index or len(guide.steps)
    names = [(s.target_part or "").strip().lower() for s in guide.steps if s.index <= last]
    return sorted({name for name in names if name})


def manual_name(label: str, names: list[str]) -> str:
    """The manual's name for a label ("replacement battery" is "battery"), "" when it has none."""
    label = label.strip().lower()
    matches = [name for name in names if label and (name in label or label in name)]
    return max(matches, key=len, default="")


def is_target(label: str, target: str) -> bool:
    """True when a mark's name is the part this step works on."""
    label, target = label.strip().lower(), target.strip().lower()
    return bool(target) and (target in label or label in target)


def marks_stages(
    job_dir: Path,
    settings: Settings,
    frame: bytes,
    step_index: int = 0,
    region: list[int] | None = None,
    client: Any = None,
) -> Iterator[tuple[bool, list[LivePart]]]:
    """The parts on one frame, like the landing photos: (False, cut out), then (True, confirmed).

    The check is the longest wait, so the cut-outs are shown first, marked as still being checked.
    """
    try:
        guide = artifacts.load(job_dir, Guide)
    except ArtifactError as exc:
        raise LiveError(f"no guide for this job: {exc}") from exc
    if guide.safety is not None and guide.safety.level == "professional_only":
        yield True, []
        return
    frame_path = save_frame(job_dir, frame, "marks.jpg")
    calls = _count_call(job_dir)
    image = cv2.imread(str(frame_path))
    if image is None:
        raise LiveError("could not read the frame")
    client = client or _coach_client(job_dir, settings)
    crop, shown = close_up(image, region or [])
    crop_path = job_dir / "live" / "close_up.jpg"
    with artifacts.atomic_path(crop_path) as tmp:
        cv2.imwrite(str(tmp), crop)
    step = next((s for s in guide.steps if s.index == step_index), None)
    target = (step.target_part or "").strip() if step else ""
    subject = guide.identity.object_name if guide.identity else guide.device
    action = f" Now: {step.title}." if step else ""
    names = manual_parts(guide, step_index)
    context = (
        f"A {subject} being repaired.{action} Parts already taken off and lying beside it are "
        "still real parts of it."
    )
    if names:
        query = (
            f"each of these parts of the {subject} that you can clearly see: {', '.join(names)}. "
            "One box per part, labelled with exactly one of these names; leave out everything else"
        )
    else:
        query = (
            f"every distinct part of the {subject} that you can clearly see, one box per part, "
            "each labelled with its own short specific name"
        )

    def to_parts(marks: list[dict]) -> list[LivePart]:
        sx, sy = (shown[2] - shown[0]) / 1000, (shown[3] - shown[1]) / 1000

        def back(x: int, y: int) -> list[int]:
            return [round(shown[0] + x * sx), round(shown[1] + y * sy)]

        return [
            LivePart(
                label=mark["label"],
                target=is_target(mark["label"], target),
                box=back(*mark["cut_box"][:2]) + back(*mark["cut_box"][2:]),
                outline=[back(x, y) for x, y in mark["outline"]],
                confidence=mark["confidence"],
            )
            for mark in marks
        ]

    try:
        grounded = client.ground(
            crop_path, query, context=context, max_boxes=MAX_PARTS, effort=GROUND_EFFORT
        )
        if names:  # a name outside the manual is a wrong name: never shown
            grounded = [
                SimpleNamespace(label=manual_name(g.label, names), box=g.box)
                for g in grounded
                if manual_name(g.label, names)
            ]
        marks = cut_marks(client, crop_path, crop, grounded) if grounded else []
        if marks:
            yield False, to_parts(marks)
        checked = confirm(client, settings.spark_model, crop, marks, context)
    except BudgetExceeded as exc:
        raise LiveError(f"could not mark the parts: {exc}") from exc
    except MetaError:  # the coach keeps coaching: only the marks are lost, never an unchecked one
        yield True, []
        return
    finally:
        artifacts.write_text_atomic(job_dir / "live" / "calls.txt", f"{calls + 1}\n")
    yield True, to_parts([mark for mark in checked if mark.get("checked")])


def live_marks(
    job_dir: Path,
    settings: Settings,
    frame: bytes,
    step_index: int = 0,
    region: list[int] | None = None,
    client: Any = None,
) -> list[LivePart]:
    """Only the parts Spark confirmed on one frame."""
    stages = marks_stages(job_dir, settings, frame, step_index, region, client)
    return [stage for stage in stages][-1][1]


def live_turn(
    job_dir: Path,
    settings: Settings,
    frame: bytes,
    last_step: int = 0,
    client: Any = None,
    pending_step: int = 0,
) -> LiveAnswer:
    """Answer one camera frame: step, status, what to say, what to do next, where the object is."""
    try:
        guide = artifacts.load(job_dir, Guide)
    except ArtifactError as exc:
        raise LiveError(f"no guide for this job: {exc}") from exc
    safety = guide.safety
    if safety is not None and safety.level == "professional_only":
        reason = safety.reasons[0] if safety.reasons else PROFESSIONAL_LINE
        return LiveAnswer(step=0, status="unclear", say=reason, next="", confidence=1)
    frame_path = save_frame(job_dir, frame)
    calls = _count_call(job_dir)
    client = client or _coach_client(job_dir, settings)
    photos = [
        step
        for step in nearby_steps(guide, last_step)
        if step.image and (job_dir / step.image).is_file()
    ]
    prompt = build_prompt(guide, last_step, photos)
    try:
        data = spark.ask_json(
            client,
            settings,
            name="live_turn",
            schema=LIVE_JSON_SCHEMA,
            prompt=prompt,
            images=[frame_path, *(job_dir / step.image for step in photos)],
            max_output_tokens=12000,  # reasoning counts against this: a low cap leaves no answer
            timeout_s=30,
            effort="low",
        )
    except SparkAnswerError as exc:
        raise LiveError(f"Spark returned an invalid live answer: {exc}") from exc
    except (BudgetExceeded, MetaError) as exc:
        raise LiveError(f"could not answer the frame: {exc}") from exc
    if not isinstance(data, dict):
        raise LiveError("Spark returned an invalid live answer")
    data = dict(data)
    data["object_box"] = object_region(data.get("object_box"))
    try:
        seen = max(0, min(int(data.get("step", 0)), len(guide.steps)))
        data["confidence"] = max(0.0, min(float(data.get("confidence", 0)), 1.0))
    except (TypeError, ValueError) as exc:
        raise LiveError("Spark returned an invalid live answer: bad step") from exc
    step, pending = settle_step(last_step, pending_step, seen, data["confidence"])
    data.update(step=step, seen=seen, pending=pending)
    if pending:  # the words are about a step the coach has not moved to yet: stay quiet
        data.update(status="unclear", say="", next="")
    try:
        answer = LiveAnswer.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise LiveError(f"Spark returned an invalid live answer: {first['msg']}") from exc
    artifacts.write_text_atomic(job_dir / "live" / "calls.txt", f"{calls + 1}\n")
    return answer
