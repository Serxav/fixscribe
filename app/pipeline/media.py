"""Stills from the original upload, at native resolution.

Keyframes and SAM need every pixel the phone captured, so stills are read
from the untouched original (never from the 720p working proxy), with the
rotation tag applied and HDR colour converted exactly as in ingest.
"""

from pathlib import Path

from PIL import Image

from app import artifacts
from app.pipeline.ingest import color_filter, run_ffmpeg
from app.schemas import SourceVideo


def _scale_max_side(max_side: int) -> str:
    return f"scale=w='if(gt(iw,ih),min({max_side},iw),-2)':h='if(gt(iw,ih),-2,min({max_side},ih))'"


def extract_still(
    original: Path,
    source: SourceVideo,
    t: float,
    dst: Path,
    max_side: int | None = None,
) -> tuple[int, int]:
    """Write one frame at ``t`` seconds from the original as an atomic PNG."""
    if t < 0:
        raise ValueError("t must be >= 0")
    if max_side is not None and max_side <= 0:
        raise ValueError("max_side must be positive")
    chain = ",".join(
        part
        for part in (color_filter(source), _scale_max_side(max_side) if max_side else "")
        if part
    )
    with artifacts.atomic_path(dst) as tmp:
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            str(t),
            "-i",
            str(original),
        ]
        if chain:
            cmd += ["-vf", chain]
        cmd += ["-frames:v", "1", str(tmp)]
        run_ffmpeg(cmd)
    with Image.open(dst) as image:
        return image.size


def extract_stills(
    original: Path,
    source: SourceVideo,
    times: list[float],
    out_dir: Path,
    max_side: int | None = None,
) -> list[Path]:
    """Write one PNG per time in ``times`` and return the paths, in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, t in enumerate(times, start=1):
        path = out_dir / f"still_{index:03d}.png"
        extract_still(original, source, t, path, max_side)
        paths.append(path)
    return paths
