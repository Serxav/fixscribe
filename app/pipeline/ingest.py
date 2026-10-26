"""First pipeline stage: check, normalize and extract audio from the upload.

Real phone video is variable frame rate, often HDR and often rotated. This
stage makes it boring: the working proxy ``video.mp4`` is constant frame rate
with true timestamps and BT.709 SDR colour, while the uploaded original is
never touched (stills and SAM read it later at native resolution).
"""

import json
import os
import statistics
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app import artifacts
from app.config import Settings
from app.schemas import IngestInfo, SourceVideo

OUT_FPS = 30
MIN_FPS = 15
SCALE_720P = "scale=w='if(gt(iw,ih),-2,min(720,iw))':h='if(gt(iw,ih),min(720,ih),-2)'"
# Measured on this machine (see tasks/018-media-ladder.md report): with fast=1
# the filter skips the primaries/gamma conversion and saturation stays -26 %
# off the SDR twin; without it the error is -0.1 % (factory fixture) and
# +0.8 % on a file tagged with a real HLG transfer. The tonemap chains kept
# saturation but crushed mean brightness from 128 to 40-85, so they lost.
HDR_TO_SDR = "colorspace=all=bt709:iall=bt2020:format=yuv420p"
_HDR_TRANSFERS = ("arib-std-b67", "smpte2084")


class IngestError(Exception):
    """A user-facing error: the uploaded video cannot be ingested."""


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float
    width: int
    height: int
    has_audio: bool


def run_ffmpeg(args: list[str], timeout_s: int = 600) -> None:
    """Run ffmpeg, turning environment and failure modes into IngestError."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        raise IngestError("ffmpeg is not installed") from None
    except subprocess.TimeoutExpired:
        raise IngestError("ffmpeg took too long") from None
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()[-3:]
        if lines:
            raise IngestError("ffmpeg failed:\n" + "\n".join(lines))
        raise IngestError("ffmpeg failed")


def find_original(job_dir: Path) -> Path:
    """Return the single `original.*` upload in the job folder."""
    matches = sorted(p for p in job_dir.glob("original.*") if p.is_file())
    if not matches:
        raise IngestError(f"no original video found in {job_dir}")
    if len(matches) > 1:
        raise IngestError(f"multiple original videos found in {job_dir}")
    return matches[0]


def _ffprobe_json(path: Path) -> dict:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise IngestError("not a readable video") from None
    if proc.returncode != 0:
        raise IngestError("not a readable video")
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise IngestError("not a readable video") from None


def _rotation_degrees(stream: dict) -> int:
    """Display rotation in degrees (0, 90, 180, 270) from the stream tags."""
    for side_data in stream.get("side_data_list", []) or []:
        try:
            angle = float(side_data.get("rotation", 0))
        except (TypeError, ValueError):
            continue
        if angle:
            return int(round(angle)) % 360
    try:
        return int(str((stream.get("tags", {}) or {}).get("rotate", 0))) % 360
    except ValueError:
        return 0


def _parse_rate(value: object) -> float:
    """Parse an ffprobe frame rate such as ``30000/1001`` into a float."""
    try:
        num, _, den = str(value).partition("/")
        return float(num) / float(den) if den else float(num)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _detect_vfr(path: Path) -> bool:
    """True when the first ~300 packet timestamps are not evenly spaced."""
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-read_intervals",
                "%+#300",
                "-show_entries",
                "packet=pts_time",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    try:
        pts = sorted(float(line) for line in proc.stdout.split())
    except ValueError:
        return False
    deltas = [b - a for a, b in zip(pts, pts[1:], strict=False) if b > a]
    if len(deltas) < 10:
        return False
    median = statistics.median(deltas)
    if median <= 0:
        return False
    off = sum(1 for d in deltas if abs(d - median) > 0.10 * median)
    return off / len(deltas) > 0.05


def _video_stream(data: dict) -> dict:
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise IngestError("not a readable video")
    return video


def probe_source(path: Path) -> SourceVideo:
    """Describe the uploaded file as it really is, before any conversion."""
    data = _ffprobe_json(path)
    video = _video_stream(data)
    try:
        width = int(video["width"])
        height = int(video["height"])
        duration_s = float(data.get("format", {}).get("duration") or video.get("duration"))
    except (KeyError, TypeError, ValueError):
        raise IngestError("not a readable video") from None
    rotation = _rotation_degrees(video)
    if rotation in (90, 270):
        width, height = height, width
    color_transfer = str(video.get("color_transfer", "") or "")
    color_primaries = str(video.get("color_primaries", "") or "")
    return SourceVideo(
        filename=path.name,
        width=width,
        height=height,
        rotation=rotation,
        fps=_parse_rate(video.get("avg_frame_rate")),
        vfr=_detect_vfr(path),
        codec=str(video.get("codec_name", "") or ""),
        pix_fmt=str(video.get("pix_fmt", "") or ""),
        color_transfer=color_transfer,
        color_primaries=color_primaries,
        hdr=color_transfer in _HDR_TRANSFERS or color_primaries == "bt2020",
        duration_s=duration_s,
    )


def _has_audio(data: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def probe(path: Path) -> VideoInfo:
    """Read duration, display size and audio presence with ffprobe."""
    source = probe_source(path)
    return VideoInfo(
        duration_s=source.duration_s,
        width=source.width,
        height=source.height,
        has_audio=_has_audio(_ffprobe_json(path)),
    )


def output_fps(source: SourceVideo) -> int:
    """The constant rate of the working proxy: 30, or the source rate if lower."""
    if source.fps <= 0 or source.fps >= OUT_FPS:
        return OUT_FPS
    return max(MIN_FPS, round(source.fps))


def color_filter(source: SourceVideo) -> str:
    """The HDR-to-SDR conversion for this source, or empty for SDR input."""
    return HDR_TO_SDR if source.hdr else ""


def normalize_video(src: Path, dst: Path, source: SourceVideo) -> None:
    """Transcode to a CFR BT.709 mp4 at most 720 on the short side."""
    chain = ",".join(part for part in (color_filter(source), SCALE_720P) if part)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vf",
            chain,
            "-fps_mode",
            "cfr",
            "-r",
            str(output_fps(source)),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "60",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-movflags",
            "+faststart",
            str(dst),
        ]
    )


def extract_audio(src: Path, dst: Path) -> None:
    """Extract mono 16-bit 24 kHz WAV for transcription."""
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )


def _convert(make: Callable[[Path], None], tmp: Path, final: Path) -> None:
    """Build the output at a tmp path, then move it atomically into place."""
    try:
        make(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, final)


def run(job_dir: Path, settings: Settings) -> IngestInfo:
    """Ingest the upload: normalize to a CFR mp4, extract WAV, record ingest.json."""
    src = find_original(job_dir)
    source = probe_source(src)
    if source.duration_s > settings.max_video_seconds:
        raise IngestError(
            f"video too long: {source.duration_s:g} s (max {settings.max_video_seconds} s)"
        )
    has_audio = _has_audio(_ffprobe_json(src))
    _convert(
        lambda tmp: normalize_video(src, tmp, source),
        job_dir / "video.tmp.mp4",
        job_dir / "video.mp4",
    )
    if has_audio:
        _convert(
            lambda tmp: extract_audio(src, tmp),
            job_dir / "audio.tmp.wav",
            job_dir / "audio.wav",
        )
    out = probe_source(job_dir / "video.mp4")
    info = IngestInfo(
        duration_s=out.duration_s,
        width=out.width,
        height=out.height,
        has_audio=_has_audio(_ffprobe_json(job_dir / "video.mp4")),
        fps=out.fps,
        source=source,
    )
    artifacts.save(job_dir, info)
    return info
