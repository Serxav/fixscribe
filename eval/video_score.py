"""Score the fasteners a job found against points placed by hand on frames of its video.

Usage:
    python -m eval.video_score                  # the key in eval/video_key.json
    python -m eval.video_score path/to/key.json

The key gives, per step, a video time and a point on every fastener of that step clearly
visible then ("find"), plus points on fasteners that may be marked without being wrong
("optional", e.g. fasteners from an earlier step). The job's ``steps/NN_fasteners.json``
gives the kept fasteners at that time. A mark finds a point inside its box (with a small
margin); a mark on no point is a false mark. Steps where nothing is visible must stay empty.
"""

import json
import sys
from pathlib import Path

from app.config import get_settings
from app.pipeline.fasteners import load_found

ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "eval" / "video_key.json"
MARGIN = 6  # pixels of the key's frame size


def covers(box: tuple, x: float, y: float) -> bool:
    return box[0] - MARGIN <= x <= box[2] + MARGIN and box[1] - MARGIN <= y <= box[3] + MARGIN


def score_step(marks: list[tuple], answer: dict) -> dict:
    find = answer.get("find", [])
    optional = answer.get("optional", [])
    found = sum(any(covers(m, x, y) for m in marks) for x, y in find)
    false = sum(not any(covers(m, x, y) for x, y in find + optional) for m in marks)
    return {"expected": len(find), "found": found, "marks": len(marks), "false": false}


def main(argv: list[str]) -> int:
    key = json.loads((Path(argv[0]) if argv else KEY).read_text(encoding="utf-8"))
    job_dir = get_settings().jobs_dir / key["job"]
    width, height = key["size"]
    total = {"expected": 0, "found": 0, "marks": 0, "false": 0}
    for index, answer in key["steps"].items():
        found = load_found(job_dir, int(index))
        marks = []
        if found is not None:
            sx, sy = width / found.size[0], height / found.size[1]
            marks = [
                (x1 * sx, y1 * sy, x2 * sx, y2 * sy)
                for x1, y1, x2, y2 in found.boxes_at(answer["t"]).values()
            ]
        result = score_step(marks, answer)
        for name in total:
            total[name] += result[name]
        ok = result["found"] == result["expected"] and result["false"] == 0
        print(
            f"{'ok' if ok else '--'} step {index:>2}  found {result['found']}/{result['expected']}"
            f"  marks {result['marks']}  false {result['false']}"
            + ("" if found is not None else "  (no fasteners file)")
        )
    recall = total["found"] / total["expected"] if total["expected"] else 1.0
    precision = (total["marks"] - total["false"]) / total["marks"] if total["marks"] else 1.0
    print(json.dumps({"recall": round(recall, 3), "precision": round(precision, 3), **total}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
