"""The sample guide visitors can open without filming anything: read-only, shipped in demo/."""

import re
import shutil
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def seed(settings: Settings, source: Path | None = None) -> bool:
    """Copy the sample guide into the jobs folder once; True when it had to be copied."""
    if not settings.demo_job:
        return False
    origin = (source or ROOT / "demo") / settings.demo_job
    target = settings.jobs_dir / settings.demo_job
    if (target / "guide.json").is_file() or not (origin / "guide.json").is_file():
        return False
    shutil.copytree(origin, target, dirs_exist_ok=True)
    return True


def ready_sample(settings: Settings) -> str:
    """The sample guide's id when it can be opened, else ""."""
    job = settings.demo_job
    return job if job and (settings.jobs_dir / job / "guide.json").is_file() else ""


def is_write_to_sample(method: str, path: str, job: str) -> bool:
    """True for a change to the sample guide. The coach's own routes only read it."""
    if not job or method in ("GET", "HEAD", "OPTIONS"):
        return False
    return bool(re.match(rf"^/(guides|api/jobs)/{re.escape(job)}(/|$)", path))
