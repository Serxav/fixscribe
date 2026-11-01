"""Copy a finished job into demo/<id> without what visitors never need.

python -m scripts.pack_demo data/jobs/<id>

Only pack a video you have the right to publish: everything in demo/ goes public.
"""

import shutil
import sys
from pathlib import Path

LEFT_OUT = (
    "original.*", "audio.wav", "live", "voice", "runner.log", "agent.log", "state.json", "*.lock",
    "spend.*", "*_raw.txt",
)  # fmt: skip


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
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1024**2
    print(f"{target}: {size:.0f} MB. Set DEMO_JOB={source.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
