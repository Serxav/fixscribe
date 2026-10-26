"""Refine stage: a second, focused Spark pass on short timecoded clips.

For the few steps that fusion left uncertain (or that remove screws), this
stage cuts a short clip of the step from the working proxy, burns the absolute
video time into every frame with OpenCV, and asks Muse Spark to re-read that
one step. Spark sees more frames per second of action and reads exact times
from the image instead of guessing them from the whole video.

The stage is optional and owns only ``refine.json``. A step that fails (bad
answer, Meta error, unreadable clip) is listed in ``skipped`` and the stage
continues; when the spend budget is reached it stops cleanly with the steps
refined so far. Temporary clips live in ``job_dir / "refine"`` and are always
deleted at the end.
"""

import json
import subprocess
from pathlib import Path

import cv2

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.meta_client import BudgetExceeded, MetaClient, MetaError
from app.schemas import (
    REFINE_JSON_SCHEMA,
    Analysis,
    DraftStep,
    Fusion,
    IngestInfo,
    Refine,
    RefinedStep,
    Transcript,
    Turn,
)


class RefineError(Exception):
    """Raised when a clip cannot be built or Spark's answer is unusable."""


VERSION = "1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "refine_v1.md"

MAX_STEPS = 4
MAX_CLIP_S = 30.0
CLIP_PAD_S = 2.0
CONFIDENCE_THRESHOLD = 0.6
MAX_OUTPUT_TOKENS = 8000
REFINE_TIMEOUT_S = 300.0

TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "refined_step",
        "schema": REFINE_JSON_SCHEMA,
        "strict": True,
    }
}


def _ordered_drafts(analysis: Analysis) -> list[DraftStep]:
    """Draft steps in Spark's time order (the order fusion numbers them in)."""
    return sorted(analysis.steps, key=lambda step: float(step.start_s))


def select_steps(analysis: Analysis, fusion: Fusion | None) -> list[int]:
    """Indexes (1-based, time order) of the steps worth a second Spark pass.

    A step is selected when its fused confidence is below
    ``CONFIDENCE_THRESHOLD`` or it removes screws. The fused confidence is
    used when fusion ran, otherwise Spark's own confidence. Lowest
    confidence first, at most ``MAX_STEPS`` steps.
    """
    fused = {step.index: step for step in fusion.steps} if fusion is not None else {}
    selected: list[tuple[float, int]] = []
    for index, draft in enumerate(_ordered_drafts(analysis), start=1):
        fused_step = fused.get(index)
        confidence = (
            float(fused_step.confidence) if fused_step is not None else float(draft.confidence)
        )
        if confidence < CONFIDENCE_THRESHOLD or draft.screw_count > 0:
            selected.append((confidence, index))
    selected.sort(key=lambda item: (item[0], item[1]))
    return [index for _confidence, index in selected[:MAX_STEPS]]


def clip_window(start: float, end: float, duration: float) -> tuple[float, float]:
    """The clip window of a step: ``[start - 2, end + 2]`` clamped to the video.

    The window is at most ``MAX_CLIP_S`` seconds; a longer step is centred
    in its window. The returned window never leaves ``[0, duration]``.
    """
    start = float(start)
    end = float(end)
    duration = float(duration)
    if duration <= 0:
        return (0.0, 0.0)
    a = max(0.0, start - CLIP_PAD_S)
    b = min(duration, end + CLIP_PAD_S)
    if b - a <= MAX_CLIP_S:
        return (a, b)
    centre = (start + end) / 2.0
    width = min(MAX_CLIP_S, duration)
    a = min(max(centre - width / 2.0, 0.0), duration - width)
    return (a, a + width)


def _draw_timecode(frame, t: float) -> None:  # type: ignore[no-untyped-def]
    """Draw ``t=<seconds> s`` as white text on a dark rounded box, top-left."""
    text = f"t={t:.1f} s"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.75
    thickness = 2
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    pad_x, pad_y = 10, 8
    x0, y0 = 12, 12
    box_w = text_w + 2 * pad_x
    box_h = text_h + baseline + 2 * pad_y
    radius = min(8, box_h // 2)
    dark = (0, 0, 0)
    # A filled rounded box: two overlapping rectangles plus four corner discs.
    cv2.rectangle(frame, (x0 + radius, y0), (x0 + box_w - radius, y0 + box_h), dark, -1)
    cv2.rectangle(frame, (x0, y0 + radius), (x0 + box_w, y0 + box_h - radius), dark, -1)
    for cx, cy in (
        (x0 + radius, y0 + radius),
        (x0 + box_w - radius, y0 + radius),
        (x0 + radius, y0 + box_h - radius),
        (x0 + box_w - radius, y0 + box_h - radius),
    ):
        cv2.circle(frame, (cx, cy), radius, dark, -1)
    cv2.putText(
        frame,
        text,
        (x0 + pad_x, y0 + pad_y + text_h),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def make_timecoded_clip(proxy: Path, a: float, b: float, dst: Path, short_side: int = 480) -> Path:
    """Cut ``[a, b]`` from ``proxy`` with the absolute time burned into each frame.

    Frames are read with OpenCV (the proxy is constant frame rate, so
    ``CAP_PROP_POS_MSEC`` is the true time of each frame), resized so the
    short side is ``short_side`` pixels, stamped, and encoded with ffmpeg
    through a rawvideo pipe (our ffmpeg has no ``drawtext``).
    """
    a = float(a)
    b = float(b)
    if a < 0:
        raise RefineError("clip start must be >= 0")
    if b <= a:
        raise RefineError("clip end must be after clip start")
    if short_side <= 0:
        raise ValueError("short_side must be positive")
    capture = cv2.VideoCapture(str(proxy))
    if not capture.isOpened():
        capture.release()
        raise RefineError(f"cannot read {proxy.name}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not fps or fps != fps or fps <= 0:  # missing or NaN
            fps = 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            ok, first = capture.read()
            if not ok or first is None:
                raise RefineError(f"cannot read {proxy.name}")
            height, width = first.shape[:2]
            # Rewind so the first frame is not lost.
            capture.set(cv2.CAP_PROP_POS_MSEC, a * 1000.0)
        scale = short_side / min(width, height)
        out_w = max(2, int(round(width * scale / 2.0)) * 2)
        out_h = max(2, int(round(height * scale / 2.0)) * 2)
        dst.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{out_w}x{out_h}",
            "-r",
            f"{fps:g}",
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ]
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        except FileNotFoundError:
            raise RefineError("ffmpeg is not installed") from None
        frames = 0
        error: RefineError | None = None
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, a * 1000.0)
            while True:
                pos_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                if pos_ms == pos_ms and pos_ms >= 0:  # not NaN
                    t = pos_ms / 1000.0
                else:
                    t = a + frames / fps
                if frames > 0 and t >= b:
                    break
                if t < a - 0.5:
                    # The seek landed early; skip until the window starts.
                    continue
                if frame.shape[1] != out_w or frame.shape[0] != out_h:
                    frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
                _draw_timecode(frame, t)
                try:
                    assert process.stdin is not None
                    process.stdin.write(frame.tobytes())
                except (BrokenPipeError, OSError):
                    break
                frames += 1
        finally:
            stderr = b""
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                error = RefineError("ffmpeg took too long")
            if process.stderr is not None:
                stderr = process.stderr.read() or b""
        if error is not None:
            raise error
        if process.returncode != 0:
            tail = stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
            raise RefineError("ffmpeg failed:\n" + "\n".join(tail) if tail else "ffmpeg failed")
        if frames == 0:
            raise RefineError(f"no readable frame in {proxy.name} at {a:.1f} s")
        return dst
    finally:
        capture.release()


def build_prompt(draft: DraftStep, start_s: float, end_s: float, turns: list[Turn]) -> str:
    """Fill the refine prompt template for one draft step and its window turns."""
    if turns:
        turns_text = "\n".join(
            f"- [{float(turn.start_s):.1f}–{float(turn.end_s):.1f} s] {turn.text}" for turn in turns
        )
    else:
        turns_text = "- (none)"
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("<<TITLE>>", draft.title)
    prompt = prompt.replace("<<INSTRUCTION>>", draft.instruction)
    prompt = prompt.replace("<<START_S>>", f"{float(start_s):.1f}")
    prompt = prompt.replace("<<END_S>>", f"{float(end_s):.1f}")
    prompt = prompt.replace("<<SCREWS>>", str(draft.screw_count))
    prompt = prompt.replace("<<TURNS>>", turns_text)
    return prompt


def build_input(prompt: str, file_id: str) -> list[dict]:
    """Video-understanding input: a text prompt plus the uploaded clip."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_file", "file_id": file_id},
            ],
        }
    ]


def parse_refined(text: str, index: int) -> RefinedStep:
    """Parse Spark's strict JSON answer into a RefinedStep or raise RefineError."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise RefineError("Spark returned an invalid refined step") from exc
    if not isinstance(data, dict):
        raise RefineError("Spark returned an invalid refined step")
    try:
        return RefinedStep.model_validate({**data, "index": int(index)})
    except Exception as exc:
        raise RefineError("Spark returned an invalid refined step") from exc


def refine_step(
    client,  # type: ignore[no-untyped-def]
    settings: Settings,
    clip_path: Path,
    index: int,
    draft: DraftStep,
    fused_start: float,
    fused_end: float,
    window: tuple[float, float],
    turns: list[Turn] | None = None,
) -> RefinedStep:
    """Ask Spark about one timecoded clip and sanity-check its answer.

    The uploaded file is always deleted, even when the call fails. An answer whose times fall
    outside the clip window (or are inverted) raises RefineError: the caller skips the step.
    """
    a, b = float(window[0]), float(window[1])
    prompt = build_prompt(draft, fused_start, fused_end, list(turns or []))
    file_id = client.upload_file(clip_path)
    try:
        response = client.respond(
            model=settings.spark_model,
            input=build_input(prompt, file_id),
            text=TEXT_FORMAT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            timeout_s=REFINE_TIMEOUT_S,
            retry_timeouts=False,
        )
    finally:
        client.delete_file(file_id)
    refined = parse_refined(response.output_text or "", index)
    inside = a - 1e-6 <= refined.start_s and refined.end_s <= b + 1e-6
    if not inside or refined.end_s <= refined.start_s:
        # Spark described a moment outside the clip it was shown: its text cannot be trusted
        # for this step either, so the whole answer is dropped and the step stays as it was.
        raise RefineError("answer outside the clip")
    return refined


def _turns_in_window(transcript: Transcript | None, a: float, b: float) -> list[Turn]:
    """Spoken turns that overlap the clip window ``[a, b]``."""
    if transcript is None:
        return []
    return [
        turn for turn in transcript.turns if float(turn.start_s) <= b and float(turn.end_s) >= a
    ]


def _short_reason(exc: BaseException) -> str:
    """One short line for ``skipped``: the error text, or its class name."""
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text[:120]


def run(job_dir: Path, settings: Settings, client=None) -> Refine:  # type: ignore[no-untyped-def]
    """Refine the selected steps of one job and save ``refine.json``.

    ``analysis.json`` and ``ingest.json`` are required; ``fusion.json`` and
    ``transcript.json`` are optional. The working proxy is ``video.mp4``.
    """
    try:
        analysis = artifacts.load(job_dir, Analysis)
        ingest = artifacts.load(job_dir, IngestInfo)
        fusion = artifacts.load_optional(job_dir, Fusion)
        transcript = artifacts.load_optional(job_dir, Transcript)
    except ArtifactError as exc:
        raise RefineError(str(exc)) from None

    result = Refine()
    selected = select_steps(analysis, fusion)
    if not selected:
        artifacts.save(job_dir, result)
        return result

    proxy = job_dir / "video.mp4"
    if not proxy.is_file():
        result.skipped.extend(f"step {index}: missing video.mp4" for index in selected)
        artifacts.save(job_dir, result)
        return result

    if client is None:
        client = MetaClient(settings, job_dir=job_dir)

    drafts = _ordered_drafts(analysis)
    fused = {step.index: step for step in fusion.steps} if fusion is not None else {}
    clip_dir = job_dir / "refine"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    try:
        for index in selected:
            draft = drafts[index - 1]
            fused_step = fused.get(index)
            fused_start = (
                float(fused_step.start_s) if fused_step is not None else float(draft.start_s)
            )
            fused_end = float(fused_step.end_s) if fused_step is not None else float(draft.end_s)
            window = clip_window(fused_start, fused_end, float(ingest.duration_s))
            clip_path = clip_dir / f"step_{index:02d}.mp4"
            clips.append(clip_path)
            try:
                make_timecoded_clip(proxy, window[0], window[1], clip_path)
                refined = refine_step(
                    client,
                    settings,
                    clip_path,
                    index,
                    draft,
                    fused_start,
                    fused_end,
                    window,
                    _turns_in_window(transcript, window[0], window[1]),
                )
            except BudgetExceeded:
                # Stop cleanly: keep what was refined and pay for nothing more.
                break
            except (MetaError, RefineError, ValueError, OSError) as exc:
                result.skipped.append(f"step {index}: {_short_reason(exc)}")
                continue
            result.steps.append(refined)
    finally:
        for clip_path in clips:
            clip_path.unlink(missing_ok=True)
        # Remove the temp folder only when nothing else lives in it.
        try:
            clip_dir.rmdir()
        except OSError:
            pass
    artifacts.save(job_dir, result)
    return result
