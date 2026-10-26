"""Job folders in data/jobs/<id>/ and their status.json, always written atomically."""

import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

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


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to a temp file in the same folder, then rename it over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, path)


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
    current = read_status(job_id, jobs_dir)
    data = current.model_dump() | changes | {"updated_at": now_iso()}
    status = JobStatus.model_validate(data)
    write_json_atomic(job_dir(job_id, jobs_dir) / "status.json", status.model_dump())
    return status


def jobs_created_today(jobs_dir: Path = JOBS_DIR) -> int:
    """Count jobs created today (UTC), to enforce DAILY_JOB_LIMIT."""
    if not jobs_dir.exists():
        return 0
    today = now_iso()[:10]
    count = 0
    for folder in jobs_dir.iterdir():
        path = folder / "status.json"
        if JOB_ID_PATTERN.fullmatch(folder.name) and path.exists():
            if JobStatus.model_validate_json(path.read_text()).created_at[:10] == today:
                count += 1
    return count
