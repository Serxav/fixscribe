"""Run the pipeline stages of one job, in order, in its own process.

The web app starts a job with `start_job(job_id)`, which launches
`python -m app.pipeline.runner <job_id>`. A failing stage marks the job as failed with a short
message; it never crashes the web server.
"""

import fcntl
import logging
import subprocess
import sys
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.jobs import JOBS_DIR, JobStatus, job_dir, update_status

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[Path, Any], Any]
    weight: float = 1.0  # share of the progress bar
    optional: bool = False  # if it fails, keep going and add a warning


def default_stages() -> list[Stage]:
    """The stages that exist so far, in pipeline order (see docs/ARCHITECTURE.md).

    Weights are rough shares of the waiting time, so the progress bar moves evenly.
    """
    from app.pipeline import analyze, guide, ingest, scenes, transcribe

    return [
        Stage("ingest", ingest.run, weight=1.0),
        Stage("transcribe", transcribe.run, weight=1.0),
        Stage("scenes", scenes.run, weight=0.2),
        Stage("analyze", analyze.run, weight=6.0),
        Stage("guide", guide.run, weight=0.2),
    ]


class JobAlreadyRunning(Exception):
    pass


@contextmanager
def job_lock(folder: Path) -> Iterator[None]:
    """Hold run.lock while the job runs. The OS releases it if the process dies."""
    with open(folder / "run.lock", "a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise JobAlreadyRunning(f"job {folder.name} is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def is_running(job_id: str, jobs_dir: Path = JOBS_DIR) -> bool:
    """True if a runner process holds the lock (a crashed runner does not)."""
    folder = job_dir(job_id, jobs_dir)
    try:
        with job_lock(folder):
            return False
    except JobAlreadyRunning:
        return True


def short_error(stage: Stage, exc: BaseException) -> str:
    message = f"{stage.name} failed: {exc}" if str(exc) else f"{stage.name} failed"
    return message[:MAX_ERROR_CHARS]


def run_job(
    job_id: str,
    settings: "Settings",
    stages: list[Stage] | None = None,
    jobs_dir: Path = JOBS_DIR,
) -> JobStatus:
    stages = default_stages() if stages is None else stages
    folder = job_dir(job_id, jobs_dir)
    total = sum(stage.weight for stage in stages) or 1.0
    with job_lock(folder):
        update_status(job_id, jobs_dir, state="running", error=None, warnings=[], progress=0.0)
        done = 0.0
        warnings: list[str] = []
        for stage in stages:
            update_status(job_id, jobs_dir, stage=stage.name, progress=done / total)
            try:
                stage.run(folder, settings)
            except Exception as exc:
                logger.error(
                    "job %s: stage %s failed\n%s", job_id, stage.name, traceback.format_exc()
                )
                if not stage.optional:
                    return update_status(
                        job_id, jobs_dir, state="failed", error=short_error(stage, exc)
                    )
                warnings.append(short_error(stage, exc))
                update_status(job_id, jobs_dir, warnings=warnings)
            done += stage.weight
        return update_status(job_id, jobs_dir, state="done", stage=None, progress=1.0)


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
