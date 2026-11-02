"""Copy a finished job into demo/<id> without what visitors never need.

python -m scripts.pack_demo data/jobs/<id>

Only pack a video you have the right to publish: everything in demo/ goes public.
"""

import shutil
import subprocess
import sys
from pathlib import Path

LEFT_OUT = (
    "original.*", "audio.wav", "live", "voice", "runner.log", "agent.log", "state.json", "*.lock",
    "spend.*", "*_raw.txt",
    "checks",  # photos visitors took to check a step: theirs, never public
    "agent",  # the agent's working folder, with its own frames and turns
    "*.before*",  # backups made by hand
)  # fmt: skip
MAX_FILE_MB = 90  # GitHub refuses a file over 100 MB
SHRINK_CRF = "30"


def shrink(video: Path) -> None:
    """Re-encode the video smaller in place. Same frames and timing, so every second still fits."""
    smaller = video.with_name("video.small.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", SHRINK_CRF, "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(smaller)],
        check=True,
    )  # fmt: skip
    smaller.replace(video)


def too_big(folder: Path) -> list[Path]:
    """Files GitHub would refuse."""
    limit = MAX_FILE_MB * 1024**2
    return [f for f in folder.rglob("*") if f.is_file() and f.stat().st_size > limit]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    source = Path(argv[0]).resolve()
    if not (source / "guide.json").is_file():
        print(f"no finished guide in {source}")
        return 1
    target = Path("demo") / source.name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*LEFT_OUT))
    video = target / "video.mp4"
    if video in too_big(target):
        print(f"{video} is over {MAX_FILE_MB} MB: making it smaller")
        shrink(video)
    left = too_big(target)
    if left:
        print("still too big for GitHub: " + ", ".join(str(f) for f in left))
        return 1
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1024**2
    print(f"{target}: {size:.0f} MB. Set DEMO_JOB={source.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
