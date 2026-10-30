"""The exam a real run must pass: does the guide mark the right part on a real repair video?

The key holds points placed by hand on frames of one job. Each question asks for a part at a
second of the video. It passes when the kept cut-out covers the point; a question with no point
passes when nothing is kept. Without --real nothing is called and the plan and its size are shown.

    python -m eval.part_exam data/jobs/<id> eval/part_key_iphone.json          # no Meta call
    python -m eval.part_exam data/jobs/<id> eval/part_key_iphone.json --real   # spends credits
"""

import json
import shutil
import sys
from pathlib import Path

import cv2

from app.config import get_settings
from app.meta_client import make_client
from app.pipeline.locate import cut_and_check, read_moments

PASS_FOUND = 0.8  # share of the visible parts that must be marked correctly


def covers(box: tuple, point: tuple[int, int]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def score(results: list[dict]) -> dict:
    """Found: right mark on a visible part. Wrong: a mark on the wrong place, or on nothing."""
    visible = [r for r in results if r["point"]]
    right = [r for r in visible if r["box"] and covers(r["box"], r["point"])]
    wrong = [r for r in results if r["box"] and not (r["point"] and covers(r["box"], r["point"]))]
    share = len(right) / len(visible) if visible else 0.0
    return {
        "found": len(right),
        "visible": len(visible),
        "wrong": len(wrong),
        "passed": share >= PASS_FOUND and not wrong,
    }


def main(argv: list[str]) -> int:
    real = "--real" in argv
    args = [a for a in argv if a != "--real"]
    if len(args) != 2:
        print(__doc__)
        return 2
    job_dir, key = Path(args[0]), json.loads(Path(args[1]).read_text(encoding="utf-8"))
    questions = key["questions"]
    if not real:
        print(f"{len(questions)} questions on {job_dir}. Add --real to ask Meta.")
        return 0
    settings = get_settings()
    client = make_client(settings, job_dir=None)
    work = job_dir / "exam"
    work.mkdir(exist_ok=True)
    results = []
    for n, question in enumerate(questions):
        at, frame = read_moments(job_dir / "video.mp4", [question["t_s"]])[0]
        path = work / f"{n}.jpg"
        cv2.imwrite(str(path), frame)
        tried: dict = {}
        kept = cut_and_check(client, settings, path, frame, question["part"], key["context"], tried)
        results.append({**question, "at": at, "box": kept[0] if kept else None, "tried": tried})
        print(question["part"], question["t_s"], tried)
    shutil.rmtree(work, ignore_errors=True)
    print(score(results))
    return 0 if score(results)["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
