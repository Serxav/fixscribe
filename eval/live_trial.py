"""Walk the live coach through a finished job's video, on a copy, and save the photos to check.

python -m eval.live_trial data/jobs/<id>                  # no Meta call: shows the plan
python -m eval.live_trial data/jobs/<id> --real           # every step, spends credits
python -m eval.live_trial data/jobs/<id> 3 8 --real       # only these steps

Each frame is taken halfway through a step, the coach stands on the step before, and the raw step
Spark sees is compared with the real one. The guide's photos come from this same video, so this
is the easy case: a user's own camera will be harder.
"""

import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from app import artifacts
from app.config import get_settings
from app.meta_client import make_client
from app.pipeline.live import LiveError, live_marks, live_turn
from app.schemas import Guide

CAP_USD = 0.6
ORANGE = (31, 90, 255)


def grab(video: Path, seconds: float, target: Path) -> bytes:
    """One video frame as JPEG bytes."""
    command = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{seconds:.2f}", "-i", str(video)]
    subprocess.run([*command, "-frames:v", "1", "-q:v", "2", str(target)], check=True)
    return target.read_bytes()


def draw(frame: Path, parts, target: Path) -> None:
    """The frame with the coach's cut-outs and names."""
    image = cv2.imread(str(frame))
    height, width = image.shape[:2]
    for part in parts:
        points = np.array([[x * width // 1000, y * height // 1000] for x, y in part.outline])
        cv2.polylines(image, [points], True, ORANGE, 3 if part.target else 2)
        x, y = points.min(axis=0)
        name = ("* " if part.target else "") + part.label
        cv2.putText(image, name, (int(x), max(16, int(y) - 6)), 0, 0.55, (255, 255, 255), 2)
    cv2.imwrite(str(target), image)


def main(argv: list[str]) -> int:
    real = "--real" in argv
    args = [a for a in argv if a != "--real"]
    if not args:
        print(__doc__)
        return 2
    source = Path(args[0]).resolve()
    guide = artifacts.load(source, Guide)
    wanted = {int(a) for a in args[1:]} or {step.index for step in guide.steps}
    steps = [step for step in guide.steps if step.index in wanted]
    if not real:
        for step in steps:
            print(step.index, step.title, (step.start_s + step.end_s) / 2)
        return 0
    copy = source.parent.parent / "close_look" / f"live_{source.name}"
    shutil.rmtree(copy, ignore_errors=True)
    (copy / "live").mkdir(parents=True)
    shutil.copy(source / "guide.json", copy / "guide.json")
    shutil.copytree(source / "steps", copy / "steps")
    settings = replace(get_settings(), live_budget_usd=CAP_USD)
    client = make_client(replace(settings, job_budget_usd=CAP_USD), job_dir=copy / "live")
    right = 0
    times = []
    for step in steps:
        shot = copy / f"camera_{step.index:02d}.jpg"
        frame = grab(source / "video.mp4", (step.start_s + step.end_s) / 2, shot)
        started = time.monotonic()
        try:
            answer = live_turn(copy, settings, frame, step.index - 1, client)
            times.append(time.monotonic() - started)
            started = time.monotonic()
            parts = live_marks(copy, settings, frame, step.index, answer.object_box, client)
        except LiveError as exc:
            print(step.index, "failed:", exc)
            continue
        marks_time = time.monotonic() - started
        right += answer.seen == step.index
        draw(copy / "live" / "marks.jpg", parts, copy / f"coach_{step.index:02d}.jpg")
        names = [("*" if p.target else "") + p.label for p in parts]
        print(
            f"real {step.index} seen {answer.seen} {answer.status} {answer.confidence:.2f} "
            f"{times[-1]:.1f}s marks {marks_time:.1f}s {names} | {answer.say}"
        )
    median = sorted(times)[len(times) // 2] if times else 0
    spent = client.job_spend.total()
    print(f"steps right {right}/{len(steps)}, median step answer {median:.1f}s, spent ${spent:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
