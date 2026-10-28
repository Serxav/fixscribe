"""Score the perception stage of a finished job: fasteners found per step against the count.

Usage:
    python -m eval.perception_score data/jobs/<id>

For every step that puts in or takes out fasteners, the count from the plan is the target and
the fasteners SAM found (and Spark confirmed) are the answer. Prints each step and the total
error (sum of |found - counted|); 0 means every step found exactly as many as it should.
"""

import sys
from pathlib import Path

from app import artifacts
from app.schemas import Perception, Plan


def score(job_dir: Path) -> dict:
    plan = artifacts.load(job_dir, Plan)
    seen = {step.index: step for step in artifacts.load(job_dir, Perception).steps}
    rows = []
    for step in plan.steps:
        counted = step.screws.count if step.screws else 0
        if not counted:
            continue
        found = len(seen[step.index].removed) if step.index in seen else 0
        rows.append({"step": step.index, "title": step.title, "counted": counted, "found": found})
    return {
        "steps": rows,
        "error": sum(abs(r["found"] - r["counted"]) for r in rows),
        "counted": sum(r["counted"] for r in rows),
        "exact": sum(r["found"] == r["counted"] for r in rows),
        "parts": sum(1 for s in seen.values() if s.part is not None),
        "looked": len(seen),
    }


def main(argv: list[str]) -> int:
    result = score(Path(argv[0]))
    for row in result["steps"]:
        flag = "ok" if row["found"] == row["counted"] else "--"
        print(
            f"{flag} step {row['step']:>2} {row['title'][:40]:<40} {row['found']}/{row['counted']}"
        )
    print(
        f"error {result['error']} on {result['counted']} fasteners, "
        f"{result['exact']}/{len(result['steps'])} steps exact, "
        f"part found on {result['parts']}/{result['looked']} steps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
