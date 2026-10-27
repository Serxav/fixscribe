"""Run the pipeline stages of one job, in order, in its own process.

The web app starts a job with `start_job(job_id)`, which launches
`python -m app.pipeline.runner <job_id>`. A failing stage marks the job as failed with a short
message; it never crashes the web server.
"""

import fcntl
import logging
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app import artifacts
from app.jobs import (
    JOBS_DIR,
    JobStatus,
    job_dir,
    now_iso,
    read_status,
    seconds_since_update,
    update_status,
)
from app.schemas import Manifest, StageRecord

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 300
LOCK_TRIES = 10
STALE_AFTER_S = 120  # a queued job that never started, or a dead runner


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[Path, Any], Any]
    weight: float = 1.0  # share of the progress bar
    optional: bool = False  # if it fails, keep going and add a warning
    output: str | None = None  # the one artifact this stage owns (deleted before it runs)
    version: str = "1"


def stage_of(
    name: str, module: Any, output: str, *, weight: float, optional: bool = False
) -> Stage:
    return Stage(
        name,
        module.run,
        weight=weight,
        optional=optional,
        output=output,
        version=getattr(module, "VERSION", "1"),
    )


def default_stages() -> list[Stage]:
    """The stages that exist so far, in pipeline order (see docs/ARCHITECTURE.md).

    Weights are rough shares of the waiting time, so the progress bar moves evenly.
    """
    from app.pipeline import (
        analyze,
        frames,
        fusion,
        identify,
        ingest,
        perception,
        plan,
        publish,
        refine,
        safety_stage,
        scenes,
        signals,
        transcribe,
    )

    return [
        stage_of("ingest", ingest, "ingest.json", weight=1.0),
        stage_of("transcribe", transcribe, "transcript.json", weight=1.0, optional=True),
        stage_of("identify", identify, "identity.json", weight=0.5, optional=True),
        stage_of("signals", signals, "signals.json", weight=0.5, optional=True),
        stage_of("scenes", scenes, "scenes.json", weight=0.2),
        stage_of("analyze", analyze, "analysis.json", weight=6.0),
        stage_of("fusion", fusion, "fusion.json", weight=0.1, optional=True),
        stage_of("refine", refine, "refine.json", weight=2.0, optional=True),
        stage_of("plan", plan, "plan.json", weight=0.1),
        stage_of("safety", safety_stage, "safety.json", weight=0.1),
        stage_of("frames", frames, "frames.json", weight=1.0, optional=True),
        stage_of("perception", perception, "perception.json", weight=1.5, optional=True),
        stage_of("publish", publish, "guide.json", weight=0.1),
    ]


def attempt_stages() -> list[Stage]:
    """Stages for an attempt job: a user's own repair video compared with a reference guide."""
    from app.pipeline import attempt, ingest, transcribe

    return [
        stage_of("ingest", ingest, "ingest.json", weight=1.0),
        stage_of("transcribe", transcribe, "transcript.json", weight=1.0, optional=True),
        stage_of("attempt", attempt, "attempt_review.json", weight=6.0),
    ]


def stages_for(status: JobStatus) -> list[Stage]:
    return attempt_stages() if status.kind == "attempt" else default_stages()


class JobAlreadyRunning(Exception):
    pass


@contextmanager
def job_lock(folder: Path, tries: int = LOCK_TRIES) -> Iterator[None]:
    """Hold run.lock while the job runs. The OS releases it if the process dies."""
    with open(folder / "run.lock", "a") as lock:
        # is_running() may hold the lock for a moment: try a few times before giving up.
        for attempt in range(tries):
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if attempt == tries - 1:
                    raise JobAlreadyRunning(f"job {folder.name} is already running") from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def is_running(job_id: str, jobs_dir: Path = JOBS_DIR) -> bool:
    """True if a runner process holds the lock (a crashed runner does not)."""
    folder = job_dir(job_id, jobs_dir)
    try:
        with job_lock(folder, tries=1):  # a status check never waits
            return False
    except JobAlreadyRunning:
        return True


def check_stale(job_id: str, jobs_dir: Path = JOBS_DIR) -> JobStatus:
    """Mark a job failed if it says queued/running but no runner holds its lock any more."""
    status = read_status(job_id, jobs_dir)
    if status.state not in ("queued", "running") or is_running(job_id, jobs_dir):
        return status
    if status.state == "queued" and seconds_since_update(status) < STALE_AFTER_S:
        return status  # the runner may still be starting
    return update_status(
        job_id, jobs_dir, state="failed", error="The job stopped unexpectedly. Please try again."
    )


def short_error(stage: Stage, exc: BaseException) -> str:
    message = f"{stage.name} failed: {exc}" if str(exc) else f"{stage.name} failed"
    return message[:MAX_ERROR_CHARS]


def run_job(
    job_id: str,
    settings: "Settings",
    stages: list[Stage] | None = None,
    jobs_dir: Path = JOBS_DIR,
) -> JobStatus:
    folder = job_dir(job_id, jobs_dir)
    stages = stages_for(read_status(job_id, jobs_dir)) if stages is None else stages
    total = sum(stage.weight for stage in stages) or 1.0
    with job_lock(folder):
        update_status(job_id, jobs_dir, state="running", error=None, warnings=[], progress=0.0)
        manifest = Manifest()
        done = 0.0
        warnings: list[str] = []
        for stage in stages:
            update_status(job_id, jobs_dir, stage=stage.name, progress=done / total)
            if stage.output:
                (folder / stage.output).unlink(missing_ok=True)  # never reuse a stale result
            record, error = run_stage(stage, folder, settings)
            manifest.stages[stage.name] = record
            manifest.total_seconds = round(manifest.total_seconds + record.seconds, 3)
            manifest.total_usd = round(manifest.total_usd + record.usd, 6)
            artifacts.save(folder, manifest)
            if error is not None:
                logger.error("job %s: stage %s failed\n%s", job_id, stage.name, error[1])
                if not stage.optional:
                    return update_status(
                        job_id, jobs_dir, state="failed", error=short_error(stage, error[0])
                    )
                warnings.append(short_error(stage, error[0]))
                update_status(job_id, jobs_dir, warnings=warnings)
            done += stage.weight
        return update_status(job_id, jobs_dir, state="done", stage=None, progress=1.0)


def run_stage(
    stage: Stage, folder: Path, settings: Any
) -> tuple[StageRecord, tuple[Exception, str] | None]:
    """Run one stage and measure it: wall time and the money this job spent during it."""
    started_at = now_iso()
    usd_before = job_usd(folder)
    t0 = time.perf_counter()
    error = None
    try:
        stage.run(folder, settings)
    except Exception as exc:
        error = (exc, traceback.format_exc())
    record = StageRecord(
        status="failed" if error else "done",
        version=stage.version,
        started_at=started_at,
        seconds=round(time.perf_counter() - t0, 3),
        usd=round(max(0.0, job_usd(folder) - usd_before), 6),
        error=short_error(stage, error[0]) if error else None,
    )
    return record, error


def job_usd(folder: Path) -> float:
    """Money spent by this job so far (the per-job spend counter of the Meta client)."""
    from app.meta_client import SpendCounter

    return SpendCounter(folder / "spend.json", budget_usd=float("inf")).total()


def start_job(job_id: str, jobs_dir: Path = JOBS_DIR) -> subprocess.Popen:
    """Launch the runner for one job in a separate process and return at once."""
    folder = job_dir(job_id, jobs_dir)
    # The child gets its own copy of the log file, so we can close ours right away.
    with open(folder / "runner.log", "a") as log:
        return subprocess.Popen(
            [sys.executable, "-m", "app.pipeline.runner", job_id, str(jobs_dir)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (1, 2):
        print("usage: python -m app.pipeline.runner <job_id> [jobs_dir]")
        return 2
    jobs_dir = Path(args[1]) if len(args) == 2 else JOBS_DIR
    logging.basicConfig(level=logging.INFO)
    try:
        status = run_job(args[0], get_settings(), jobs_dir=jobs_dir)
    except (JobAlreadyRunning, FileNotFoundError, ValueError) as exc:
        print(exc)
        return 1
    print(f"job {status.job_id}: {status.state}")
    return 0 if status.state == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
