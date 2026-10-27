"""Shared route helpers: from a job id in a URL to its folder and guide, in one place."""

from pathlib import Path

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.jobs import job_dir
from app.schemas import Guide


def job_folder(job_id: str, settings: Settings) -> Path | None:
    """The job's folder, or None when the id is not a valid job id (it comes from a URL)."""
    try:
        return job_dir(job_id, settings.jobs_dir)
    except ValueError:
        return None


def load_guide(job_id: str, settings: Settings) -> tuple[Path | None, Guide | None]:
    """(folder, guide): folder is None for a bad id; guide is None when not ready or unreadable."""
    folder = job_folder(job_id, settings)
    if folder is None:
        return None, None
    try:
        return folder, artifacts.load_optional(folder, Guide)
    except ArtifactError:
        return folder, None
