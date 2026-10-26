"""Score a generated guide against the step times and screw counts written by hand.

Usage:
    python -m eval.score data/jobs/<id>/guide.json samples/<name>.expected.json

Expected file format (screws is optional):
    {"steps": [{"title": "Remove back cover", "start_s": 3.0, "end_s": 15.5, "screws": 4}]}
"""

import json
import sys
from pathlib import Path

from app.schemas import Guide

BOUNDARY_TOLERANCE_S = 2.0
MATCH_IOU = 0.3  # a found step and an expected step are "the same step" above this overlap


def iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Temporal intersection over union of two time ranges (0 = no overlap, 1 = identical)."""
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return overlap / union if union > 0 else 0.0


def match_steps(found: list[dict], expected: list[dict]) -> list[tuple[int, int, float]]:
    """Pair found and expected steps by best overlap, each step used once.

    Returns (found_pos, expected_pos, iou) sorted by expected position.
    """
    pairs = [
        (iou(f["start_s"], f["end_s"], e["start_s"], e["end_s"]), fi, ei)
        for fi, f in enumerate(found)
        for ei, e in enumerate(expected)
    ]
    used_found, used_expected, matches = set(), set(), []
    for score, fi, ei in sorted(pairs, reverse=True):
        if score < MATCH_IOU or fi in used_found or ei in used_expected:
            continue
        used_found.add(fi)
        used_expected.add(ei)
        matches.append((fi, ei, score))
    return sorted(matches, key=lambda m: m[1])


def guide_steps(guide: Guide) -> list[dict]:
    return [
        {
            "title": step.title,
            "start_s": step.start_s,
            "end_s": step.end_s,
            "screws": step.screws.count if step.screws else 0,
        }
        for step in guide.steps
    ]


def score(found: list[dict], expected: list[dict]) -> dict:
    matches = match_steps(found, expected)
    rows = []
    for fi, ei, overlap in matches:
        f, e = found[fi], expected[ei]
        start_err = abs(f["start_s"] - e["start_s"])
        end_err = abs(f["end_s"] - e["end_s"])
        rows.append(
            {
                "expected": ei + 1,
                "found": fi + 1,
                "title": e["title"],
                "iou": round(overlap, 2),
                "start_error_s": round(start_err, 2),
                "end_error_s": round(end_err, 2),
                "boundary_hit": start_err <= BOUNDARY_TOLERANCE_S
                and end_err <= BOUNDARY_TOLERANCE_S,
                "screws_expected": e.get("screws"),
                "screws_found": f.get("screws", 0),
            }
        )

    n_match = len(matches)
    precision = n_match / len(found) if found else 0.0
    recall = n_match / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    screw_rows = [r for r in rows if r["screws_expected"] is not None]
    return {
        "expected_steps": len(expected),
        "found_steps": len(found),
        "matched_steps": n_match,
        "step_precision": round(precision, 3),
        "step_recall": round(recall, 3),
        "step_f1": round(f1, 3),
        "mean_iou": round(sum(r["iou"] for r in rows) / n_match, 3) if n_match else 0.0,
        "boundary_hit_rate": round(sum(r["boundary_hit"] for r in rows) / len(expected), 3)
        if expected
        else 0.0,
        "mean_start_error_s": round(sum(r["start_error_s"] for r in rows) / n_match, 2)
        if n_match
        else None,
        "screw_count_accuracy": round(
            sum(r["screws_found"] == r["screws_expected"] for r in screw_rows) / len(screw_rows), 3
        )
        if screw_rows
        else None,
        "rows": rows,
    }


def format_report(result: dict) -> str:
    lines = [
        "| # | title | IoU | start err (s) | end err (s) | ±2 s | screws (found/expected) |",
        "|---|-------|-----|---------------|-------------|------|--------------------------|",
    ]
    for r in result["rows"]:
        screws = f"{r['screws_found']}/{r['screws_expected']}" if r["screws_expected"] else "-"
        hit = "yes" if r["boundary_hit"] else "no"
        lines.append(
            f"| {r['expected']} | {r['title']} | {r['iou']} | {r['start_error_s']} | "
            f"{r['end_error_s']} | {hit} | {screws} |"
        )
    lines += [
        "",
        f"Steps: {result['matched_steps']} matched, {result['found_steps']} found, "
        f"{result['expected_steps']} expected (F1 {result['step_f1']})",
        f"Mean IoU: {result['mean_iou']}  Boundaries within ±2 s: {result['boundary_hit_rate']}",
        f"Screw count accuracy: {result['screw_count_accuracy']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m eval.score <guide.json> <expected.json>")
        return 2
    guide = Guide.model_validate_json(Path(args[0]).read_text())
    expected = json.loads(Path(args[1]).read_text())["steps"]
    print(format_report(score(guide_steps(guide), expected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
