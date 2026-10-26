"""Run the whole pipeline on every labelled video and write one dated results file.

Usage:
    .venv/bin/python -m eval.run_eval --confirm-spend          # real Meta calls (costs money)
    .venv/bin/python -m eval.run_eval --reuse                  # score the last run, no calls

A labelled video is `samples/<name>.mp4|.mov` next to `samples/<name>.expected.json`:
    {"steps": [{"title": "Remove back cover", "start_s": 3.0, "end_s": 15.5, "screws": 4}]}

Results go to `eval/results/<UTC time>_<label>.json` with, per video and in total: step F1,
mean IoU, boundaries within ±2 s, screw count accuracy, screws located by SAM, seconds and dollars
per stage (from the job's manifest.json). Compare two results files to compare two versions.
"""

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import artifacts
from app.config import Settings, get_settings
from app.jobs import create_job
from app.pipeline.runner import run_job
from app.schemas import Guide, Manifest
from eval.score import guide_steps, score

VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
RESULTS_DIR = Path("eval/results")


def labelled_videos(samples: Path) -> list[tuple[Path, Path]]:
    """(video, expected.json) pairs, sorted by name. Videos without labels are skipped."""
    pairs = []
    for video in sorted(samples.iterdir()):
        expected = video.with_suffix(".expected.json")
        if video.suffix.lower() in VIDEO_SUFFIXES and expected.is_file():
            pairs.append((video, expected))
    return pairs


def run_pipeline(video: Path, settings: Settings, jobs_dir: Path) -> Path:
    """Process one video as a new job and return its folder."""
    job_id = create_job(jobs_dir).job_id
    shutil.copy(video, jobs_dir / job_id / f"original{video.suffix.lower()}")
    run_job(job_id, settings, jobs_dir=jobs_dir)
    return jobs_dir / job_id


def evaluate_job(job: Path, expected_path: Path) -> dict[str, Any]:
    """Score one finished job folder against its labels."""
    expected = json.loads(expected_path.read_text())["steps"]
    status = json.loads((job / "status.json").read_text())
    row: dict[str, Any] = {"job": job.name, "state": status["state"], "error": status["error"]}
    manifest = artifacts.load_optional(job, Manifest)
    if manifest:
        row["seconds"] = manifest.total_seconds
        row["usd"] = manifest.total_usd
        row["stages"] = {
            name: {"seconds": r.seconds, "usd": r.usd, "status": r.status}
            for name, r in manifest.stages.items()
        }
    guide = artifacts.load_optional(job, Guide)
    if guide is None:
        return row
    found = guide_steps(guide)
    result = score(found, expected)
    row.update({key: value for key, value in result.items() if key != "rows"})
    row["rows"] = result["rows"]
    located = sum(len(step.screws.boxes) for step in guide.steps if step.screws)
    labelled = sum(step.get("screws") or 0 for step in expected)
    row["screws_labelled"] = labelled
    row["screws_located_by_sam"] = located
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Averages over the videos that produced a guide; totals for time and money."""
    scored = [row for row in rows if "step_f1" in row]

    def mean(key: str) -> float | None:
        values = [row[key] for row in scored if row.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "videos": len(rows),
        "guides": len(scored),
        "step_f1": mean("step_f1"),
        "mean_iou": mean("mean_iou"),
        "boundary_hit_rate": mean("boundary_hit_rate"),
        "screw_count_accuracy": mean("screw_count_accuracy"),
        "seconds": round(sum(row.get("seconds", 0.0) for row in rows), 2),
        "usd": round(sum(row.get("usd", 0.0) for row in rows), 4),
    }


def run_eval(
    samples: Path,
    jobs_dir: Path,
    *,
    label: str,
    reuse: dict[str, Path] | None = None,
    process: Callable[[Path], Path] | None = None,
) -> dict[str, Any]:
    rows = []
    for video, expected in labelled_videos(samples):
        job = reuse.get(video.name) if reuse else None
        if job is None:
            if process is None:
                raise ValueError(f"{video.name} has no previous job: run with --confirm-spend")
            job = process(video)
        rows.append({"video": video.name, **evaluate_job(job, expected)})
    return {
        "label": label,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summarize(rows),
        "videos": rows,
    }


def last_jobs(results_dir: Path) -> dict[str, Path]:
    """video name -> job folder of the newest results file."""
    files = sorted(results_dir.glob("*.json"))
    if not files:
        return {}
    data = json.loads(files[-1].read_text())
    return {row["video"]: Path(row["job_dir"]) for row in data["videos"] if row.get("job_dir")}


def format_table(result: dict[str, Any]) -> str:
    lines = [
        "| video | state | step F1 | IoU | ±2 s | screws (SAM / labelled) | seconds | $ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in result["videos"]:
        lines.append(
            f"| {row['video']} | {row['state']} | {row.get('step_f1', '-')} | "
            f"{row.get('mean_iou', '-')} | {row.get('boundary_hit_rate', '-')} | "
            f"{row.get('screws_located_by_sam', '-')} / {row.get('screws_labelled', '-')} | "
            f"{row.get('seconds', '-')} | {row.get('usd', '-')} |"
        )
    s = result["summary"]
    lines.append(
        f"\n{s['guides']}/{s['videos']} guides · step F1 {s['step_f1']} · IoU {s['mean_iou']} · "
        f"±2 s {s['boundary_hit_rate']} · screw accuracy {s['screw_count_accuracy']} · "
        f"{s['seconds']} s · ${s['usd']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    parser.add_argument("--label", default="run")
    parser.add_argument("--confirm-spend", action="store_true", help="allow real Meta calls")
    parser.add_argument("--reuse", action="store_true", help="score the jobs of the last run")
    args = parser.parse_args(argv)
    if not args.samples.is_dir() or not labelled_videos(args.samples):
        print(f"no labelled videos in {args.samples} (need <name>.mp4 + <name>.expected.json)")
        return 1
    if not args.confirm_spend and not args.reuse:
        print("this makes real Meta calls: add --confirm-spend (or --reuse to score the last run)")
        return 2
    settings = get_settings()
    jobs_dir = settings.data_dir / "eval_jobs"
    result = run_eval(
        args.samples,
        jobs_dir,
        label=args.label,
        reuse=last_jobs(RESULTS_DIR) if args.reuse else None,
        process=(lambda video: run_pipeline(video, settings, jobs_dir))
        if args.confirm_spend
        else None,
    )
    for row in result["videos"]:
        row["job_dir"] = str(jobs_dir / row["job"])
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    out = RESULTS_DIR / f"{stamp}_{args.label}.json"
    artifacts.write_json_atomic(out, result)
    print(format_table(result))
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
