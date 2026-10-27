"""Live mode: "where am I and what do I do now?" from one camera frame.

While the user repairs, the phone sends one frame every ~2 s. Spark looks at the
frame next to the guide and answers which step the user is on, whether it looks
right, and what to do next. One frame is kept as ``live/frame.jpg`` and the
number of Spark calls as ``live/calls.txt`` (capped, so a forgotten camera page
cannot eat the budget).
"""

import io
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps
from pydantic import Field, ValidationError

from app import artifacts, spark
from app.artifacts import ArtifactError
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaError, make_client
from app.schemas import Guide, Step, Strict, _object
from app.spark import SparkAnswerError

MAX_FRAME_BYTES = 4 * 1024**2
MAX_FRAME_SIDE = 768
MAX_LIVE_CALLS_PER_JOB = 300  # ~$0.003 each, so a session costs at most ~$1

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "live_v1.md"

PROFESSIONAL_LINE = "A qualified professional must do this repair."


class LiveError(Exception):
    """A user-facing reason the frame could not be answered."""


class LiveAnswer(Strict):
    """Which guide step the user is on, judged from one camera frame."""

    step: int = Field(ge=0)  # the guide step the user is on (0 = not started / not visible)
    status: Literal["on_track", "wrong", "done_step", "unclear"]
    say: str  # one short sentence for the voice, in the guide language (<= 20 words)
    next: str  # the next action, imperative (<= 15 words)
    look_for: str = ""  # 1-3 common English words SAM can find on the frame, or ""
    confidence: float = Field(ge=0, le=1)


LIVE_JSON_SCHEMA: dict[str, Any] = _object(
    {
        "step": {"type": "integer"},
        "status": {
            "type": "string",
            "enum": ["on_track", "wrong", "done_step", "unclear"],
        },
        "say": {"type": "string"},
        "next": {"type": "string"},
        "look_for": {"type": "string"},
        "confidence": {"type": "number"},
    }
)


def _describe_step(step: Step) -> str:
    """One prompt line per step: number, title, instruction and fasteners."""
    screws = step.screws
    if not screws or screws.count <= 0:
        fasteners = "none"
    else:
        kind = (screws.kind or "screw").strip() or "screw"
        fasteners = f"{screws.count} {kind}"
    return f"{step.index}. {step.title} — {step.instruction} — {fasteners}"


def build_prompt(guide: Guide, last_step: int = 0) -> str:
    """Fill the live prompt template with the guide language, steps and last step."""
    language = (guide.language or "").strip() or "en"
    steps_text = "\n".join(_describe_step(step) for step in guide.steps) or "(no steps)"
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("<<LANGUAGE>>", language)
    prompt = prompt.replace("<<STEPS>>", steps_text)
    return prompt.replace("<<LAST_STEP>>", str(last_step))


def save_frame(job_dir: Path, frame: bytes) -> Path:
    """Phone frame bytes to an upright JPEG (max side 768), written atomically."""
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
    dst = job_dir / "live" / "frame.jpg"
    try:
        with artifacts.atomic_path(dst) as tmp:
            upright.save(tmp, format="JPEG", quality=80)
    except OSError as exc:
        raise LiveError(f"could not save the frame: {exc}") from exc
    return dst


def read_calls(job_dir: Path) -> int:
    """How many live Spark calls this job already made (0 when unknown)."""
    try:
        return max(0, int((job_dir / "live" / "calls.txt").read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return 0


def live_turn(
    job_dir: Path,
    settings: Settings,
    frame: bytes,
    last_step: int = 0,
    client: Any = None,
) -> LiveAnswer:
    """Answer one camera frame: step, status, what to say and what to do next."""
    try:
        guide = artifacts.load(job_dir, Guide)
    except ArtifactError as exc:
        raise LiveError(f"no guide for this job: {exc}") from exc
    safety = guide.safety
    if safety is not None and safety.level == "professional_only":
        reason = safety.reasons[0] if safety.reasons else PROFESSIONAL_LINE
        return LiveAnswer(step=0, status="unclear", say=reason, next="", look_for="", confidence=1)
    frame_path = save_frame(job_dir, frame)
    calls = read_calls(job_dir)
    if calls >= MAX_LIVE_CALLS_PER_JOB:
        raise LiveError(f"live limit reached for this job ({MAX_LIVE_CALLS_PER_JOB} calls max)")
    if client is None:
        client = make_client(settings, job_dir=job_dir)
    prompt = build_prompt(guide, last_step)
    try:
        data = spark.ask_json(
            client,
            settings,
            name="live_turn",
            schema=LIVE_JSON_SCHEMA,
            prompt=prompt,
            images=[frame_path],
            max_output_tokens=4000,
            timeout_s=30,
        )
    except SparkAnswerError as exc:
        raise LiveError(f"Spark returned an invalid live answer: {exc}") from exc
    except (BudgetExceeded, MetaError) as exc:
        raise LiveError(f"could not answer the frame: {exc}") from exc
    if not isinstance(data, dict):
        raise LiveError("Spark returned an invalid live answer")
    data = dict(data)
    try:
        data["step"] = max(0, min(int(data.get("step", 0)), len(guide.steps)))
    except (TypeError, ValueError) as exc:
        raise LiveError("Spark returned an invalid live answer: bad step") from exc
    try:
        answer = LiveAnswer.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise LiveError(f"Spark returned an invalid live answer: {first['msg']}") from exc
    artifacts.write_text_atomic(job_dir / "live" / "calls.txt", f"{calls + 1}\n")
    return answer
