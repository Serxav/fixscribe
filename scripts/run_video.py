"""Run the whole pipeline on one local video (real Meta calls, they cost credits).

Usage: .venv/bin/python scripts/run_video.py samples/<name>.mp4
Then, if samples/<name>.expected.json exists, the guide is scored with eval/score.py.
"""

import json
import shutil
import sys
from pathlib import Path

from app.config import get_settings
from app.jobs import create_job
from app.meta_client import SpendCounter
from app.pipeline.runner import run_job
from app.schemas import Guide
from eval.score import format_report, guide_steps, score


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: .venv/bin/python scripts/run_video.py samples/<name>.mp4")
        return 2
    video = Path(args[0])
    if not video.is_file():
        print(f"video not found: {video}")
        return 1
    settings = get_settings()
    if not settings.model_api_key:
        print("MODEL_API_KEY is not set")
        return 1
    jobs_dir = settings.data_dir / "jobs"
    spend = SpendCounter(settings.data_dir / "spend.json", settings.budget_usd)
    before = spend.total()

    job_id = create_job(jobs_dir).job_id
    shutil.copy(video, jobs_dir / job_id / f"original{video.suffix.lower()}")
    print(f"job {job_id}: running...")
    status = run_job(job_id, settings, jobs_dir=jobs_dir)
    print(f"job {job_id}: {status.state} {status.error or ''}".rstrip())
    print(f"this video cost ${spend.total() - before:.4f} (total ${spend.total():.4f})")
    if status.state != "done":
        return 1

    guide_path = jobs_dir / job_id / "guide.json"
    guide = Guide.model_validate_json(guide_path.read_text())
    print(f"guide: {guide_path} ({len(guide.steps)} steps)")
    for check in guide.checks:
        print(f"  check: {check}")
    expected = video.with_suffix(".expected.json")
    if expected.is_file():
        print(format_report(score(guide_steps(guide), json.loads(expected.read_text())["steps"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
