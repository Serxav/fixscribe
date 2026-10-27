"""Client for the Meta Responses API with retries and a spend counter."""

import base64
import fcntl
import json
import logging
import math
import os
import random
import re
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import cv2
import httpx
import numpy as np
import openai
from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    PromptBox,
    PromptObject,
    build_object_prompt,
    decode_mask_to_raster,
    decode_mask_to_svg_path,
    image_segmentation_format,
    video_segmentation_format,
)

from app.config import Settings

logger = logging.getLogger(__name__)

# Copied from https://dev.meta.ai/docs/pricing-rate-limits
PRICES: dict[str, dict[str, float]] = {
    "muse-spark-1.3": {
        "input_per_m": 1.25,
        "cached_input_per_m": 0.15,
        "output_per_m": 4.25,
    },
    "muse-wonder-1.0": {
        "input_per_m": 4.00,
        "cached_input_per_m": 0.20,
        "output_per_m": 20.00,
    },
    "sam-3.1": {
        "per_image": 0.0025,
        "per_video_frame": 0.0002,
    },
    "muse-voice-transcribe-1.0": {
        "per_hour": 0.18,
    },
    "muse-image-1.0": {
        "per_image": 0.01,
    },
}

T = TypeVar("T")

MAX_ATTEMPTS = 4
RETRYABLE_STATUSES = (429, 500, 503)
NON_RETRYABLE_STATUSES = (400, 401, 402, 403, 404, 413, 504)
MAX_RETRY_AFTER_S = 30.0
ASR_TIMEOUT_S = 300.0


class BudgetExceeded(Exception):
    """Raised before a call when spend is already at or over budget."""


class MetaError(Exception):
    """Non-retryable Meta API failure, or retries used up."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ImagePolicyError(MetaError):
    """The image model refused the edit (400 content_policy_violation)."""


def token_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Cost in USD. `cached_tokens` is a subset of `input_tokens`.

    See https://dev.meta.ai/docs/prompt-caching
    """
    if model not in PRICES or "input_per_m" not in PRICES[model]:
        raise ValueError(f"unknown model for token pricing: {model}")
    rates = PRICES[model]
    fresh = input_tokens - cached_tokens
    return (
        fresh * rates["input_per_m"]
        + cached_tokens * rates["cached_input_per_m"]
        + output_tokens * rates["output_per_m"]
    ) / 1_000_000


def sam_cost(images: int = 0, video_frames: int = 0) -> float:
    """Cost in USD for SAM masks ($2.50/1k images, $0.20/1k frames)."""
    rates = PRICES["sam-3.1"]
    return images * rates["per_image"] + video_frames * rates["per_video_frame"]


def asr_cost(seconds: float) -> float:
    """Cost in USD for transcription, metered in whole seconds."""
    billed = math.ceil(seconds)
    return billed / 3600 * PRICES["muse-voice-transcribe-1.0"]["per_hour"]


def _wav_duration_s(wav_path: Path) -> float:
    """Duration in seconds of a WAV file, read with the standard library."""
    with wave.open(str(wav_path), "rb") as handle:
        rate = handle.getframerate()
        if not rate:
            return 0.0
        return handle.getnframes() / rate


def _parse_frame_rate(value: object) -> float:
    """Parse an ffprobe frame rate such as ``30000/1001`` into frames per second."""
    try:
        num, _, den = str(value).partition("/")
        return float(num) / float(den) if den else float(num)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _video_frame_count(path: Path) -> int:
    """Exact frame count of a clip: ffprobe `nb_read_frames`, else duration x fps."""
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames,avg_frame_rate,r_frame_rate,duration",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        raise ValueError(f"cannot read video: {path}") from None
    if proc.returncode != 0:
        raise ValueError(f"cannot read video: {path}")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise ValueError(f"cannot read video: {path}") from None
    if not isinstance(data, dict):
        raise ValueError(f"cannot read video: {path}")
    streams = data.get("streams") or []
    stream = streams[0] if streams else {}
    if not isinstance(stream, dict):
        stream = {}
    try:
        return int(stream.get("nb_read_frames"))
    except (TypeError, ValueError):
        pass
    try:
        raw_duration = stream.get("duration") or (data.get("format") or {}).get("duration")
        duration = float(raw_duration)
    except (TypeError, ValueError, AttributeError):
        raise ValueError(f"cannot count frames in video: {path}") from None
    fps = _parse_frame_rate(stream.get("avg_frame_rate")) or _parse_frame_rate(
        stream.get("r_frame_rate")
    )
    if not duration or not fps:
        raise ValueError(f"cannot count frames in video: {path}")
    return int(round(duration * fps))


def _is_number(value: Any) -> bool:
    """True for a real JSON number (bools are not numbers here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _image_mime(suffix: str) -> str:
    """MIME type for an image suffix, defaulting to JPEG for the step keyframes."""
    return _IMAGE_MIME.get(suffix.lower(), "image/jpeg")


@dataclass(frozen=True)
class Detection:
    """One SAM detection in the pixels of the image actually sent."""

    object_id: str
    box: tuple[float, float, float, float]
    confidence: float | None
    mask: bytes | None
    mask_size: tuple[int, int] | None
    mask_bounds: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class GroundBox:
    """One grounded object: label and box on the 0..1000 grid of the sent image."""

    label: str
    box: tuple[int, int, int, int]
    why: str


@dataclass(frozen=True)
class TrackedObject:
    """One SAM-tracked object in a single video frame, in source pixels."""

    object_id: int
    box: tuple[float, float, float, float]
    confidence: float | None
    mask: np.ndarray | None
    svg_path: str | None


@dataclass(frozen=True)
class FrameTrack:
    """All tracked objects in one video frame (`frame` is the `<Nf>` index)."""

    frame: int
    width: int
    height: int
    objects: list[TrackedObject]


_FRAME_HEADER_RE = re.compile(r"^<(\d+)f")
_BOX_TOKEN_RE = re.compile(r"<\|box;([^|]*)\|>")
_FRAME_WIDTH_RE = re.compile(r"(?:^|;)\s*w\s*=\s*(\d+)")
_FRAME_HEIGHT_RE = re.compile(r"(?:^|;)\s*h\s*=\s*(\d+)")


def _frame_sizes(text: str) -> dict[int, tuple[int, int]]:
    """Frame size per `<Nf>` index, read from the `w=`/`h=` fields of box tokens.

    The parser records keep box coordinates but drop the frame size, so it is
    re-extracted here from the raw answer with a narrow regex.
    """
    sizes: dict[int, tuple[int, int]] = {}
    for raw_line in text.splitlines():
        header = _FRAME_HEADER_RE.match(raw_line.strip())
        if header is None:
            continue
        frame = int(header.group(1))
        if frame in sizes:
            continue
        for token in _BOX_TOKEN_RE.finditer(raw_line):
            body = token.group(1)
            width = _FRAME_WIDTH_RE.search(body)
            height = _FRAME_HEIGHT_RE.search(body)
            if width and height:
                sizes[frame] = (int(width.group(1)), int(height.group(1)))
                break
    return sizes


def _parse_video_tracks(text: str) -> list[FrameTrack]:
    """Parse a SAM video answer into per-frame tracks sorted by frame index.

    Frames with no line in the answer are simply absent. Objects keep the wire
    order within their frame.
    """
    parser = video_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    if result.diagnostics:
        logger.warning("sam video parser diagnostics: %d", len(result.diagnostics))
    sizes = _frame_sizes(text)
    boxes: dict[int, list[Any]] = {}
    masks: dict[tuple[int, str], Any] = {}
    for record in result.records:
        frame_ref = getattr(record, "frame", None)
        if frame_ref is None:
            continue
        index = int(frame_ref.frame_index)
        if getattr(record, "kind", None) == "box":
            boxes.setdefault(index, []).append(record)
        elif getattr(record, "kind", None) == "mask":
            masks[(index, str(record.object_id))] = record
    tracks: list[FrameTrack] = []
    for index in sorted(boxes):
        size = sizes.get(index)
        if size is None:
            raise MetaError(f"sam video answer has no frame size for frame {index}")
        width, height = size
        objects: list[TrackedObject] = []
        for box_record in boxes[index]:
            mask_record = masks.get((index, str(box_record.object_id)))
            mask_array: np.ndarray | None = None
            svg_path: str | None = None
            mask_confidence: float | None = None
            if mask_record is not None:
                mask_confidence = mask_record.confidence
                try:
                    raw = decode_mask_to_raster(mask_record.mask)
                    mask_array = (
                        np.frombuffer(raw, dtype=np.uint8)
                        .reshape(int(mask_record.mask.height), int(mask_record.mask.width))
                        .astype(bool)
                    )
                except Exception:
                    mask_array = None
                try:
                    svg_path = decode_mask_to_svg_path(mask_record.mask)
                except Exception:
                    svg_path = None
            confidence = box_record.confidence
            if confidence is None:
                confidence = mask_confidence
            objects.append(
                TrackedObject(
                    object_id=int(box_record.object_id),
                    box=(
                        float(box_record.left),
                        float(box_record.top),
                        float(box_record.right),
                        float(box_record.bottom),
                    ),
                    confidence=confidence,
                    mask=mask_array,
                    svg_path=svg_path,
                )
            )
        tracks.append(FrameTrack(frame=index, width=width, height=height, objects=objects))
    return tracks


_MAX_BOX_OBJECTS = 16


def _validate_segment_concept(concept: str) -> None:
    """Reject empty concepts and anything that is not one short noun phrase."""
    if not concept or not concept.strip():
        raise ValueError("concept must not be empty")
    if any(char in concept for char in (",", ";", "+")):
        raise ValueError("concept must be one short noun phrase")


def _validate_prompt_size(size: tuple[int, int] | None) -> tuple[int, int]:
    """Clip `(width, height)` for box prompts, both positive integers."""
    if (
        not isinstance(size, (tuple, list))
        or len(size) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in size)
    ):
        raise ValueError("size must be a (width, height) tuple of positive integers")
    return (int(size[0]), int(size[1]))


def _clamp_prompt_box(edges: object, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Clamp half-open box edges inside the clip; None when nothing is left."""
    if not isinstance(edges, (tuple, list)) or len(edges) != 4:
        raise ValueError(f"box must be a (left, top, right, bottom) tuple: {edges!r}")
    for value in edges:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"box edges must be numbers: {edges!r}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"box edges must be finite numbers: {edges!r}")
    left, top, right, bottom = (int(value) for value in edges)
    left = min(max(left, 0), width)
    right = min(max(right, 0), width)
    top = min(max(top, 0), height)
    bottom = min(max(bottom, 0), height)
    if left >= right or top >= bottom:
        return None
    return (left, top, right, bottom)


def _build_box_prompt_text(
    box_list: list[tuple[int, int, tuple[int, int, int, int]]],
    size: tuple[int, int] | None,
) -> str:
    """Build the SAM `input_text` for box prompts, clamped inside `size`.

    Boxes that become empty after clamping are skipped with a warning; at
    least one must remain. Object ids are grouped so one id carries all of
    its frames in a single object, as `build_object_prompt` requires.
    """
    if size is None:
        raise ValueError("size is required with boxes")
    width, height = _validate_prompt_size(size)
    grouped: dict[Any, list[FramePrompt]] = {}
    order: list[Any] = []
    for item in box_list:
        try:
            object_id, frame, edges = item
        except (TypeError, ValueError):
            raise ValueError(f"box must be (object_id, frame, (l, t, r, b)): {item!r}") from None
        clamped = _clamp_prompt_box(edges, width, height)
        if clamped is None:
            logger.warning(
                "sam video box prompt for object %r on frame %r is empty, skipped",
                object_id,
                frame,
            )
            continue
        left, top, right, bottom = clamped
        if object_id not in grouped:
            grouped[object_id] = []
            order.append(object_id)
        grouped[object_id].append(FramePrompt(frame=frame, box=PromptBox(left, top, right, bottom)))
    if not order:
        raise ValueError("no usable box prompts: every box was empty after clamping")
    if len(order) > _MAX_BOX_OBJECTS:
        raise ValueError(f"at most {_MAX_BOX_OBJECTS} prompted objects, got {len(order)}")
    return build_object_prompt(
        size=(width, height),
        objects=[PromptObject(id=oid, prompts=grouped[oid]) for oid in order],
    )


GROUND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "x_min": {"type": "integer"},
                    "y_min": {"type": "integer"},
                    "x_max": {"type": "integer"},
                    "y_max": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["label", "x_min", "y_min", "x_max", "y_max", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["boxes"],
    "additionalProperties": False,
}

_GROUND_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "ground_v1.md"

_GRID_MAX = 1000
_MIN_GROUND_SIZE = 4


def _clamp_grid(value: float) -> int:
    """Clamp a grounding coordinate to the 0..1000 grid."""
    return min(max(int(round(value)), 0), _GRID_MAX)


def to_pixels(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    """Map a 0..1000 grid box to pixel edges, x2/y2 inclusive inside the image."""
    try:
        x_min, y_min, x_max, y_max = box
    except (TypeError, ValueError):
        raise ValueError(f"box must be a (x_min, y_min, x_max, y_max) tuple: {box!r}") from None
    for value in (x_min, y_min, x_max, y_max):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"box edges must be numbers: {box!r}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"box edges must be finite numbers: {box!r}")
    for size in (width, height):
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"size must be positive integers: {(width, height)!r}")
    xs = sorted(round(_clamp_grid(v) * (width - 1) / _GRID_MAX) for v in (x_min, x_max))
    ys = sorted(round(_clamp_grid(v) * (height - 1) / _GRID_MAX) for v in (y_min, y_max))
    return (xs[0], ys[0], xs[1], ys[1])


def _parse_ground_box(item: Any) -> GroundBox | None:
    """Normalize one grounding answer box; None when malformed or too small."""
    if not isinstance(item, dict):
        return None
    try:
        raw = [item[key] for key in ("x_min", "y_min", "x_max", "y_max")]
    except KeyError:
        return None
    edges: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        edges.append(_clamp_grid(value))
    x_min, y_min, x_max, y_max = edges
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    if x_max - x_min < _MIN_GROUND_SIZE or y_max - y_min < _MIN_GROUND_SIZE:
        return None
    return GroundBox(
        label=str(item.get("label") or ""),
        box=(x_min, y_min, x_max, y_max),
        why=str(item.get("why") or ""),
    )


def _parse_image_segmentation(text: str) -> list[Detection]:
    """Parse a SAM 3.1 image answer into detections in sent-image pixels."""
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    if result.diagnostics:
        logger.warning("sam parser diagnostics: %d", len(result.diagnostics))
    mask_by_id: dict[str, Any] = {}
    for record in result.records:
        if getattr(record, "kind", None) == "mask":
            mask_by_id.setdefault(str(record.object_id), record)
    detections: list[Detection] = []
    for record in result.records:
        if getattr(record, "kind", None) != "box":
            continue
        mask_record = mask_by_id.get(str(record.object_id))
        mask: bytes | None = None
        mask_size: tuple[int, int] | None = None
        mask_bounds: tuple[float, float, float, float] | None = None
        if mask_record is not None:
            try:
                mask = decode_mask_to_raster(mask_record.mask)
            except Exception:
                mask = None
            if mask is not None:
                mask_size = (int(mask_record.mask.width), int(mask_record.mask.height))
                bounds = mask_record.bounds
                mask_bounds = (
                    float(bounds.left),
                    float(bounds.top),
                    float(bounds.right),
                    float(bounds.bottom),
                )
        confidence = getattr(record, "confidence", None)
        detections.append(
            Detection(
                object_id=str(record.object_id),
                box=(
                    float(record.left),
                    float(record.top),
                    float(record.right),
                    float(record.bottom),
                ),
                confidence=float(confidence) if _is_number(confidence) else None,
                mask=mask,
                mask_size=mask_size,
                mask_bounds=mask_bounds,
            )
        )
    return detections


class _InvalidAsrAnswer(Exception):
    """Internal marker: ASR returned 200 with an unusable body."""


class SpendCounter:
    """Tracks spend in `data/spend.json` across restarts and processes."""

    def __init__(self, path: Path, budget_usd: float) -> None:
        self._path = path
        self._budget_usd = budget_usd

    @property
    def budget_usd(self) -> float:
        return self._budget_usd

    @property
    def _log_path(self) -> Path:
        return self._path.parent / "spend.log"

    def _totals_from_log(self) -> tuple[float, int, dict[str, float]]:
        """Sum `spend.log`, skipping broken lines."""
        total = 0.0
        calls = 0
        by_model: dict[str, float] = {}
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0.0, 0, {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    continue
                usd = float(entry["usd"])
                model = entry["model"]
                if not isinstance(model, str):
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            total += usd
            calls += 1
            by_model[model] = by_model.get(model, 0.0) + usd
        return total, calls, by_model

    def _read_totals(self) -> tuple[float, int, dict[str, float]]:
        """Read totals from `spend.json`, rebuilding from the log if corrupt."""
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise TypeError("spend.json is not an object")
            total = float(data["total_usd"])
            calls = int(data.get("calls", 0))
            raw_by_model = data.get("by_model", {})
            if not isinstance(raw_by_model, dict):
                raise TypeError("spend.json by_model is not an object")
            by_model = {str(k): float(v) for k, v in raw_by_model.items()}
            return total, calls, by_model
        except FileNotFoundError:
            if self._log_path.exists():
                return self._totals_from_log()
            return 0.0, 0, {}
        except (ValueError, TypeError, KeyError, OSError):
            logger.error("spend.json is corrupt, rebuilding total from spend.log")
            return self._totals_from_log()

    def total(self) -> float:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise TypeError("spend.json is not an object")
            return float(data["total_usd"])
        except FileNotFoundError:
            if self._log_path.exists():
                return self._totals_from_log()[0]
            return 0.0
        except (ValueError, TypeError, KeyError, OSError):
            logger.error("spend.json is corrupt, rebuilding total from spend.log")
            return self._totals_from_log()[0]

    def check(self) -> None:
        if self.total() >= self._budget_usd:
            raise BudgetExceeded(f"spend already at budget ${self._budget_usd:.2f}")

    def add(self, model: str, usd: float) -> float:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.parent / "spend.lock"
        lock_path.touch(exist_ok=True)
        with open(lock_path, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                old_total, old_calls, by_model = self._read_totals()
                # Append to the log before rewriting spend.json so a corrupt
                # spend.json can always be rebuilt.
                entry = {
                    "model": model,
                    "usd": usd,
                    "at": datetime.now(UTC).isoformat(),
                }
                with open(self._log_path, "a", encoding="utf-8") as log_file:
                    log_file.write(json.dumps(entry) + "\n")
                    log_file.flush()
                    os.fsync(log_file.fileno())
                new_total = old_total + usd
                calls = old_calls + 1
                by_model[model] = float(by_model.get(model, 0.0)) + usd
                payload = {
                    "total_usd": new_total,
                    "calls": calls,
                    "by_model": by_model,
                }
                with tempfile.NamedTemporaryFile(
                    dir=str(self._path.parent),
                    delete=False,
                    mode="w",
                    suffix=".tmp",
                    encoding="utf-8",
                ) as tmp:
                    json.dump(payload, tmp)
                    tmp_path = tmp.name
                os.replace(tmp_path, self._path)
                return new_total
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return min(value, MAX_RETRY_AFTER_S)


class MetaClient:
    """Thin wrapper over the OpenAI SDK pointed at the Meta API."""

    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        http: Any | None = None,
        job_dir: Path | None = None,
    ) -> None:
        if client is None:
            # Built exactly like https://dev.meta.ai/docs/sdks
            client = openai.OpenAI(
                api_key=settings.model_api_key,
                base_url=settings.meta_api_base,
                max_retries=0,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        if http is None:
            http = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))
        self._client = client
        self._sleep = sleep
        self._http = http
        self._settings = settings
        self.spend = SpendCounter(settings.data_dir / "spend.json", settings.budget_usd)
        # Each job also has its own cap, so one long or broken video cannot eat the budget.
        self.job_spend = (
            SpendCounter(job_dir / "spend.json", settings.job_budget_usd) if job_dir else None
        )

    def _check_budget(self) -> None:
        self.spend.check()
        if self.job_spend is not None and self.job_spend.total() >= self.job_spend.budget_usd:
            raise BudgetExceeded(
                f"this video reached its spend limit of ${self.job_spend.budget_usd:.2f}"
            )

    def _add_spend(self, model: str, usd: float) -> None:
        self.spend.add(model, usd)
        if self.job_spend is not None:
            self.job_spend.add(model, usd)

    def respond(
        self,
        *,
        model: str,
        input: Any,
        max_output_tokens: int = 4000,
        timeout_s: float | None = None,
        retry_timeouts: bool = True,
        **kwargs: Any,
    ) -> Any:
        if "input_per_m" not in PRICES.get(model, {}):
            raise ValueError(f"unknown model: {model}")
        if max_output_tokens < 4000:
            raise ValueError("max_output_tokens must be >= 4000")
        self._check_budget()

        def _do_create() -> Any:
            create_kwargs: dict[str, Any] = dict(kwargs)
            if timeout_s is not None:
                create_kwargs["timeout"] = httpx.Timeout(timeout_s, connect=10.0)
            return self._client.responses.create(
                model=model,
                input=input,
                max_output_tokens=max_output_tokens,
                **create_kwargs,
            )

        response = self._with_retries(_do_create, retry_timeouts=retry_timeouts)
        usage = response.usage
        if usage is None:
            logger.warning("response without usage, spend not counted")
            return response
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        cost = token_cost(model, usage.input_tokens, cached, usage.output_tokens)
        self._add_spend(model, cost)
        return response

    def upload_file(self, path: Path, expires_seconds: int = 86400) -> str:
        """Upload a video file for video understanding. Uploading is free."""
        if path.suffix != ".mp4":
            raise ValueError(f"only .mp4 videos can be uploaded: {path}")
        if path.stat().st_size > 1_073_741_824:
            raise ValueError(f"file is bigger than 1 GiB: {path}")

        def _do_upload() -> Any:
            with open(path, "rb") as f:
                return self._client.files.create(
                    purpose="user_data",
                    file=f,
                    expires_after={"anchor": "created_at", "seconds": expires_seconds},
                )

        return self._with_retries(_do_upload).id

    def delete_file(self, file_id: str) -> None:
        """Delete an uploaded file. Cleanup never raises."""
        try:
            self._with_retries(lambda: self._client.files.delete(file_id))
        except Exception:
            logger.warning("failed to delete file %s", file_id, exc_info=True)

    def transcribe(
        self,
        wav: Path,
        mode: str = "ENDPOINTING",
        language_bias: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> dict:
        """Transcribe a WAV file with Muse Voice Transcribe.

        See https://dev.meta.ai/docs/speech-to-text
        """
        if wav.stat().st_size > 33_554_432:
            raise ValueError(f"audio file is bigger than 32 MB: {wav}")
        self._check_budget()
        url = f"{self._settings.meta_api_base}/asr/transcribe"
        headers = {
            "Authorization": f"Bearer {self._settings.model_api_key}",
            "Accept": "application/json",
        }

        def _do_post() -> dict:
            request: dict[str, Any] = {
                "model": self._settings.asr_model,
                "audioEncoding": "WAV",
                "mode": mode,
            }
            if language_bias:
                request["languageBias"] = language_bias
            if keywords:
                request["keywords"] = keywords
            with open(wav, "rb") as f:
                files = {
                    "request": (None, json.dumps(request), "application/json"),
                    "audio": (wav.name, f, "audio/wav"),
                }
                try:
                    resp = self._http.post(
                        url,
                        headers=headers,
                        files=files,
                        timeout=httpx.Timeout(ASR_TIMEOUT_S, connect=10.0),
                    )
                except httpx.TimeoutException as exc:
                    raise openai.APITimeoutError(request=exc.request) from exc
                except httpx.TransportError as exc:
                    raise openai.APIConnectionError(message=str(exc), request=exc.request) from exc
            if resp.status_code == 429:
                raise openai.RateLimitError("asr status 429", response=resp, body=None)
            if resp.status_code >= 400:
                raise openai.APIStatusError(
                    f"asr status {resp.status_code}", response=resp, body=None
                )
            try:
                data = resp.json()
            except Exception as exc:
                raise _InvalidAsrAnswer from exc
            if not isinstance(data, dict):
                raise _InvalidAsrAnswer
            return data

        try:
            data = self._with_retries(_do_post)
        except _InvalidAsrAnswer as exc:
            self._add_spend(self._settings.asr_model, asr_cost(_wav_duration_s(wav)))
            raise MetaError("asr returned an invalid answer") from exc
        raw_duration = data.get("audioDurationMs")
        if _is_number(raw_duration):
            duration_s = float(raw_duration) / 1000
        else:
            duration_s = _wav_duration_s(wav)
            data["audioDurationMs"] = int(round(duration_s * 1000))
        self._add_spend(self._settings.asr_model, asr_cost(duration_s))
        return data

    def edit_image(self, image_path: Path, prompt: str) -> bytes:
        """Redraw a photo as an illustration with Muse Image.

        Raw JSON POST to ``/v1/images/edits`` with
        ``{"model", "prompt", "images": [{"image_url": data URL}], "n": 1,
        "output_format": "webp"}``; the answer is ``data[0].b64_json``.
        See https://dev.meta.ai/docs/image-generation

        Only 429 and 503 are retried (through the shared retry helper); a
        400 content-policy refusal raises ImagePolicyError and every other
        error raises MetaError, both without retries.
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")
        try:
            raw = Path(image_path).read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read image: {image_path}") from exc
        if not raw:
            raise ValueError(f"cannot read image: {image_path}")
        data_url = "data:" + _image_mime(Path(image_path).suffix) + ";base64,"
        data_url += base64.b64encode(raw).decode("ascii")
        self._check_budget()
        url = f"{self._settings.meta_api_base}/images/edits"
        headers = {
            "Authorization": f"Bearer {self._settings.model_api_key}",
            "Accept": "application/json",
        }
        body = {
            "model": "muse-image-1.0",
            "prompt": prompt,
            "images": [{"image_url": data_url}],
            "n": 1,
            "output_format": "webp",
        }

        def _do_post() -> bytes:
            try:
                resp = self._http.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=httpx.Timeout(120.0, connect=10.0),
                )
            except httpx.TimeoutException as exc:
                raise openai.APITimeoutError(request=exc.request) from exc
            except httpx.TransportError as exc:
                raise openai.APIConnectionError(message=str(exc), request=exc.request) from exc
            if resp.status_code == 400:
                raise ImagePolicyError(
                    f"image edit refused with status 400: {resp.text[:200]}",
                    status_code=400,
                )
            if resp.status_code == 500:
                raise MetaError("image edit failed with status 500", status_code=500)
            if resp.status_code == 429:
                raise openai.RateLimitError("image edit status 429", response=resp, body=None)
            if resp.status_code == 503:
                raise openai.APIStatusError("image edit status 503", response=resp, body=None)
            if resp.status_code >= 400:
                raise MetaError(
                    f"image edit failed with status {resp.status_code}",
                    status_code=resp.status_code,
                )
            try:
                payload = resp.json()
                return base64.b64decode(payload["data"][0]["b64_json"])
            except Exception as exc:
                raise MetaError("image edit returned an invalid answer") from exc

        result = self._with_retries(_do_post)
        self._add_spend("muse-image-1.0", PRICES["muse-image-1.0"]["per_image"])
        return result

    def _jpeg_data_url(self, image_path: Path, max_side: int) -> tuple[str, int, int]:
        """Read, downscale and JPEG-encode an image for the Meta API.

        Returns the data URL and the ``(width, height)`` of the image
        actually sent, so callers can map boxes back and forth.
        """
        if max_side <= 0:
            raise ValueError("max_side must be positive")
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"cannot read image: {image_path}")
        height, width = image.shape[:2]
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / longest
            new_width = max(1, round(width * scale))
            new_height = max(1, round(height * scale))
            image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
            height, width = image.shape[:2]
        ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise ValueError(f"cannot encode image: {image_path}")
        data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")
        return data_url, int(width), int(height)

    def _sam_image_request(
        self, data_url: str, prompt_text: str, metadata: dict[str, str]
    ) -> list[Detection]:
        """Send one SAM 3.1 image request and parse the answer into detections."""
        self._check_budget()

        def _do_create() -> Any:
            return self._client.responses.create(
                model=self._settings.sam_model,
                input=[
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt_text},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                ],
                metadata=metadata,
            )

        response = self._with_retries(_do_create)
        usage = getattr(response, "usage", None)
        raw_images = getattr(usage, "images_processed", None) if usage is not None else None
        images = raw_images if _is_number(raw_images) else 1
        self._add_spend(self._settings.sam_model, sam_cost(images=images))
        text = getattr(response, "output_text", "") or ""
        return _parse_image_segmentation(text)

    def segment(
        self, image_path: Path, concept: str, max_side: int = 1280
    ) -> tuple[list[Detection], tuple[int, int]]:
        """Segment one concept in an image with SAM 3.1.

        Returns the detections and the ``(width, height)`` of the image
        actually sent, so callers can normalize boxes.
        """
        if not concept or not concept.strip():
            raise ValueError("concept must not be empty")
        if any(char in concept for char in (",", ";", "+")):
            raise ValueError("concept must be one short noun phrase")
        data_url, width, height = self._jpeg_data_url(image_path, max_side)
        detections = self._sam_image_request(
            data_url, concept, {"mask_encoding": "one_bit", "include_confidence": "true"}
        )
        return detections, (width, height)

    def ground(
        self,
        image_path: Path,
        query: str,
        *,
        context: str = "",
        max_boxes: int = 8,
        max_side: int = 1280,
    ) -> list[GroundBox]:
        """Point at ``query`` objects in a still with Muse Spark grounding.

        Returns up to ``max_boxes`` boxes on the 0..1000 grid of the image
        actually sent, so SAM can segment exactly those boxes afterwards.
        See https://dev.meta.ai/docs/image-understanding
        """
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if max_boxes < 1:
            raise ValueError("max_boxes must be at least 1")
        data_url, _width, _height = self._jpeg_data_url(image_path, max_side)
        template = _GROUND_PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            template.replace("<<CONTEXT>>", context.strip() or "none")
            .replace("<<QUERY>>", query)
            .replace("<<MAX_BOXES>>", str(max_boxes))
        )
        response = self.respond(
            model=self._settings.spark_model,
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
                    "name": "grounding",
                    "schema": GROUND_SCHEMA,
                    "strict": True,
                }
            },
            reasoning={"effort": "medium"},
            max_output_tokens=4000,
        )
        text = getattr(response, "output_text", "") or ""
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            raise MetaError("grounding returned invalid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("boxes"), list):
            raise MetaError("grounding returned invalid JSON")
        found: list[GroundBox] = []
        for item in data["boxes"]:
            parsed = _parse_ground_box(item)
            if parsed is not None:
                found.append(parsed)
            if len(found) >= max_boxes:
                break
        return found

    def segment_boxes(
        self,
        image_path: Path,
        boxes: Sequence[tuple[int, int, int, int]],
        max_side: int = 1280,
    ) -> tuple[list[Detection], tuple[int, int]]:
        """Segment grounded boxes (0..1000 grid) in a still with SAM 3.1.

        Returns the detections and the ``(width, height)`` of the image
        actually sent. Box prompts use the ``<0f>`` frame marker with
        inclusive pixel edges; see https://dev.meta.ai/docs/sam/segmenting
        """
        box_list = list(boxes)
        if not 1 <= len(box_list) <= _MAX_BOX_OBJECTS:
            raise ValueError(
                f"segment_boxes needs 1..{_MAX_BOX_OBJECTS} boxes, got {len(box_list)}"
            )
        data_url, width, height = self._jpeg_data_url(image_path, max_side)
        prompt_text = _build_box_prompt_text(
            [
                (str(index + 1), 0, to_pixels(box, width, height))
                for index, box in enumerate(box_list)
            ],
            (width, height),
        )
        detections = self._sam_image_request(data_url, prompt_text, {"include_confidence": "true"})
        return detections, (width, height)

    def segment_video(
        self,
        video_path: Path,
        concept: str | None = None,
        *,
        boxes: Sequence[tuple[int, int, tuple[int, int, int, int]]] = (),
        size: tuple[int, int] | None = None,
        max_frames: int = 600,
    ) -> list[FrameTrack]:
        """Track one concept (or boxed objects) through a clip with SAM 3.1 video.

        Exactly one of `concept` / `boxes` must be given. A concept tracks
        every object matching a word; boxes track exactly the pointed-at
        objects, one object id per box, with the prompt text built by
        `meta_sam_parser.build_object_prompt`. Box edges are half-open
        `(left, top, right, bottom)` clamped inside `size`.

        Counts the clip frames with ffprobe, bills `max(50, frames)` video
        frames, and returns one track per answered frame sorted by frame
        index. Uses a plain (non-streaming) Responses call; the client has no
        streaming support.
        """
        box_list = list(boxes or ())
        has_concept = concept is not None
        has_boxes = len(box_list) > 0
        if has_concept == has_boxes:
            raise ValueError("exactly one of concept or boxes must be given")
        if max_frames <= 0:
            raise ValueError("max_frames must be positive")
        if has_boxes:
            prompt_text = _build_box_prompt_text(box_list, size)
            # Box/point prompts always return one_bit masks, so no
            # mask_encoding is sent; confidence as "true" strings.
            metadata = {"include_confidence": "true"}
        else:
            assert concept is not None
            _validate_segment_concept(concept)
            prompt_text = concept
            # Default propagation ("both"); confidence as "true" strings.
            metadata = {"mask_encoding": "one_bit", "include_confidence": "true"}
        frames = _video_frame_count(video_path)
        if frames > max_frames:
            raise ValueError(f"clip has {frames} frames, over max_frames={max_frames}")
        cost = sam_cost(video_frames=max(50, frames))
        self._check_budget()
        file_id = self.upload_file(video_path)
        try:

            def _do_create() -> Any:
                return self._client.responses.create(
                    model=self._settings.sam_model,
                    input=[
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": prompt_text},
                                {"type": "input_video", "file_id": file_id},
                            ],
                        }
                    ],
                    metadata=metadata,
                )

            response = self._with_retries(_do_create)
        finally:
            self.delete_file(file_id)
        self._add_spend(self._settings.sam_model, cost)
        text = getattr(response, "output_text", "") or ""
        return _parse_video_tracks(text)

    def _with_retries(self, fn: Callable[[], T], retry_timeouts: bool = True) -> T:
        last_exc: BaseException | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return fn()
            except openai.APIStatusError as exc:
                status = getattr(exc, "status_code", None)
                retryable = status in RETRYABLE_STATUSES or isinstance(exc, openai.RateLimitError)
                if not retryable:
                    logger.warning("meta api error status=%s attempt=%s", status, attempt)
                    raise MetaError(
                        f"meta api failed with status {status} on attempt {attempt}",
                        status_code=status,
                    ) from exc
                last_exc = exc
            except openai.APITimeoutError as exc:
                if not retry_timeouts:
                    raise MetaError("meta api timed out", status_code=None) from exc
                last_exc = exc
                status = None
            except openai.APIConnectionError as exc:
                last_exc = exc
                status = None
            if attempt >= MAX_ATTEMPTS:
                break
            wait = _retry_after_seconds(last_exc) if last_exc is not None else None
            if wait is None:
                wait = min(60.0, 1.0 * (2 ** (attempt - 1))) + random.uniform(0, 1)
            logger.warning("meta api error status=%s attempt=%s", status, attempt)
            self._sleep(wait)
        status = getattr(last_exc, "status_code", None)
        logger.warning("meta api error status=%s attempt=%s", status, MAX_ATTEMPTS)
        raise MetaError(
            f"meta api failed with status {status} after {MAX_ATTEMPTS} attempts",
            status_code=status,
        ) from last_exc


# --- The one switch between the real Meta API and a fake ---------------------------------------

ClientFactory = Callable[..., Any]
_factory: ClientFactory | None = None


def make_client(settings: Settings, job_dir: Path | None = None) -> Any:
    """The only way pipeline code gets a Meta client.

    Normally a real `MetaClient`. Tests and the offline demo call `set_client_factory(Fake)` once,
    so no stage can reach the real API by accident (a test fails if a stage builds MetaClient).
    """
    factory = _factory or MetaClient
    return factory(settings, job_dir=job_dir)


def set_client_factory(factory: ClientFactory | None) -> None:
    """Use `factory(settings, job_dir=...)` instead of MetaClient; None restores the real one."""
    global _factory
    _factory = factory
