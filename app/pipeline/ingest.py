"""First pipeline stage: check, normalize and extract audio from the upload."""

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings

SCALE_720P = "scale=w='if(gt(iw,ih),-2,min(720,iw))':h='if(gt(iw,ih),min(720,ih),-2)'"


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


def _is_rotated(stream: dict) -> bool:
    """True when the video stream carries a 90/270-degree rotation tag."""
    for side_data in stream.get("side_data_list", []) or []:
        try:
            angle = float(side_data.get("rotation", 0))
        except (TypeError, ValueError):
            continue
        if angle % 360 in (90, 270):
            return True
    tags = stream.get("tags", {}) or {}
    return str(tags.get("rotate")) in ("90", "270")


def probe(path: Path) -> VideoInfo:
    """Read duration, display size and audio presence with ffprobe."""
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
        data = json.loads(proc.stdout)
    except ValueError:
        raise IngestError("not a readable video") from None
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise IngestError("not a readable video")
    try:
        width = int(video["width"])
        height = int(video["height"])
        duration_s = float(data.get("format", {}).get("duration"))
    except (KeyError, TypeError, ValueError):
        raise IngestError("not a readable video") from None
    if _is_rotated(video):
        width, height = height, width
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return VideoInfo(duration_s=duration_s, width=width, height=height, has_audio=has_audio)


def normalize_video(src: Path, dst: Path) -> None:
    """Transcode to 720p mp4, never upscaling small videos."""
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vf",
            SCALE_720P,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
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


def _write_json(dst: Path, payload: dict) -> None:
    """Write a JSON sidecar atomically (tmp file + rename)."""
    tmp = dst.with_suffix(".tmp.json")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, dst)


def run(job_dir: Path, settings: Settings) -> VideoInfo:
    """Ingest the upload: normalize to 720p mp4, extract WAV, record ingest.json."""
    src = find_original(job_dir)
    info = probe(src)
    if info.duration_s > settings.max_video_seconds:
        raise IngestError(
            f"video too long: {info.duration_s:g} s (max {settings.max_video_seconds} s)"
        )
    _convert(
        lambda tmp: normalize_video(src, tmp),
        job_dir / "video.tmp.mp4",
        job_dir / "video.mp4",
    )
    if info.has_audio:
        _convert(
            lambda tmp: extract_audio(src, tmp),
            job_dir / "audio.tmp.wav",
            job_dir / "audio.wav",
        )
    out = probe(job_dir / "video.mp4")
    _write_json(
        job_dir / "ingest.json",
        {
            "duration_s": out.duration_s,
            "width": out.width,
            "height": out.height,
            "has_audio": out.has_audio,
        },
    )
    return out
