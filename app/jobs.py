"""Job folders in data/jobs/<id>/ and their status.json, always written atomically."""

import fcntl
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.artifacts import write_json_atomic

JOBS_DIR = Path("data/jobs")
JOB_ID_PATTERN = re.compile(r"[0-9a-f]{12}")


class JobStatus(BaseModel):
    job_id: str
    state: Literal["queued", "running", "done", "failed"] = "queued"
    stage: str | None = None
    progress: float = Field(default=0.0, ge=0, le=1)
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def job_dir(job_id: str, jobs_dir: Path = JOBS_DIR) -> Path:
    # The id comes from URLs, so check it before building a path (no "../").
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError(f"invalid job id: {job_id!r}")
    return jobs_dir / job_id


def create_job(jobs_dir: Path = JOBS_DIR) -> JobStatus:
    job_id = uuid.uuid4().hex[:12]
    folder = job_dir(job_id, jobs_dir)
    folder.mkdir(parents=True)
    stamp = now_iso()
    status = JobStatus(job_id=job_id, created_at=stamp, updated_at=stamp)
    write_json_atomic(folder / "status.json", status.model_dump())
    return status


def read_status(job_id: str, jobs_dir: Path = JOBS_DIR) -> JobStatus:
    path = job_dir(job_id, jobs_dir) / "status.json"
    if not path.exists():
        raise FileNotFoundError(f"job not found: {job_id}")
    return JobStatus.model_validate_json(path.read_text())


def update_status(job_id: str, jobs_dir: Path = JOBS_DIR, **changes: Any) -> JobStatus:
    # The web process and the runner can both update a job: lock the read-modify-write.
    folder = job_dir(job_id, jobs_dir)
    with open(folder / "status.lock", "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_status(job_id, jobs_dir)
        data = current.model_dump() | changes | {"updated_at": now_iso()}
        status = JobStatus.model_validate(data)
        write_json_atomic(folder / "status.json", status.model_dump())
        return status


def seconds_since_update(status: JobStatus) -> float:
    return (datetime.now(UTC) - datetime.fromisoformat(status.updated_at)).total_seconds()


def jobs_created_today(jobs_dir: Path = JOBS_DIR) -> int:
    """Count jobs created today (UTC), to enforce DAILY_JOB_LIMIT."""
    if not jobs_dir.exists():
        return 0
    today = now_iso()[:10]
    count = 0
    for folder in jobs_dir.iterdir():
        path = folder / "status.json"
        if not (JOB_ID_PATTERN.fullmatch(folder.name) and path.exists()):
            continue
        try:
            created = JobStatus.model_validate_json(path.read_text()).created_at
        except (OSError, ValueError):
            continue  # one broken job folder must not block every upload
        if created[:10] == today:
            count += 1
    return count
