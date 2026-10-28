"""Score part detections against points placed by hand on the same photos.

Usage:
    python -m eval.detect_score                      # the landing photos in web/static/photos
    python -m eval.detect_score path/to/photos_dir   # any folder of <name>.json files

The answer key (eval/detect_key.json) gives, for each photo, one point on every part the
search should find ("find") and on parts it may find without being wrong ("optional").
Points and outlines use the 0..1000 grid. A mark finds a point when the point lies inside
its outline (with a small margin). A mark that covers no point is a false mark; a mark that
covers two or more "find" points merged several parts into one.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "eval" / "detect_key.json"
PHOTOS = ROOT / "web" / "static" / "photos"
MARGIN = 8  # grid units a point may lie outside an outline and still count


def covers(mark: dict, x: float, y: float) -> bool:
    """True when the point is inside the mark's outline (or its box when it has none)."""
    if mark.get("outline"):
        contour = np.array(mark["outline"], dtype=np.float32).reshape(-1, 1, 2)
        return cv2.pointPolygonTest(contour, (float(x), float(y)), True) >= -MARGIN
    x0, y0, x1, y1 = mark["cut_box"]
    return x0 - MARGIN <= x <= x1 + MARGIN and y0 - MARGIN <= y <= y1 + MARGIN


def score_photo(marks: list[dict], key: dict) -> dict:
    """Found / missed points and false / merged marks for one photo."""
    find = key.get("find", [])
    optional = key.get("optional", [])
    found = [any(covers(m, x, y) for m in marks) for _, x, y in find]
    false, merged = [], []
    for i, mark in enumerate(marks):
        hits = sum(covers(mark, x, y) for _, x, y in find)
        extra = sum(covers(mark, x, y) for _, x, y in optional)
        if hits + extra == 0:
            false.append(i)
        if hits >= 2:
            merged.append(i)
    return {
        "expected": len(find),
        "found": sum(found),
        "missed": [find[i][0] for i, ok in enumerate(found) if not ok],
        "marks": len(marks),
        "false": false,
        "merged": merged,
    }


def summary(results: dict[str, dict]) -> dict:
    expected = sum(r["expected"] for r in results.values())
    found = sum(r["found"] for r in results.values())
    marks = sum(r["marks"] for r in results.values())
    bad = sum(len(r["false"]) + len(r["merged"]) for r in results.values())
    return {
        "recall": round(found / expected, 3) if expected else 0.0,
        "precision": round((marks - bad) / marks, 3) if marks else 0.0,
        "perfect": sum(
            r["found"] == r["expected"] and not r["false"] and not r["merged"]
            for r in results.values()
        ),
        "photos": len(results),
    }


def main(argv: list[str]) -> int:
    folder = Path(argv[0]) if argv else PHOTOS
    key = json.loads(KEY.read_text(encoding="utf-8"))
    results = {}
    for name, answer in key.items():
        path = folder / f"{name}.json"
        if not path.exists():
            continue
        marks = json.loads(path.read_text(encoding="utf-8"))["marks"]
        results[name] = score_photo(marks, answer)
    for name, r in results.items():
        flag = "ok" if r["found"] == r["expected"] and not r["false"] and not r["merged"] else "--"
        print(
            f"{flag} {name:<11} found {r['found']}/{r['expected']}  marks {r['marks']}"
            f"  false {len(r['false'])}  merged {len(r['merged'])}  missed {r['missed']}"
        )
    print(json.dumps(summary(results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
