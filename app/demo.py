"""The sample guides visitors can open without filming anything: read-only, shipped in demo/.

DEMO_JOB names one folder under demo/, or several separated by commas; the first is the one the
landing features, and every one of them opens in the app.
"""

import json
import re
import shutil
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def sample_ids(value: str) -> list[str]:
    """The sample folder names in a DEMO_JOB value, in order, without blanks or repeats."""
    ids: list[str] = []
    for part in value.split(","):
        name = part.strip()
        if name and re.fullmatch(r"[A-Za-z0-9_-]+", name) and name not in ids:
            ids.append(name)
    return ids


def is_sample(job: str, value: str) -> bool:
    """True when this job folder is one of the read-only samples."""
    return job in sample_ids(value)


def seed(settings: Settings, source: Path | None = None) -> bool:
    """Copy each sample guide into the jobs folder once; True when any had to be copied."""
    copied = False
    for job in sample_ids(settings.demo_job):
        origin = (source or ROOT / "demo") / job
        target = settings.jobs_dir / job
        if (target / "guide.json").is_file() or not (origin / "guide.json").is_file():
            continue
        shutil.copytree(origin, target, dirs_exist_ok=True)
        copied = True
    return copied


def ready_samples(settings: Settings) -> list[str]:
    """The sample guides that can be opened now, the featured one first."""
    return [
        j for j in sample_ids(settings.demo_job) if (settings.jobs_dir / j / "guide.json").is_file()
    ]


def ready_sample(settings: Settings) -> str:
    """The featured sample guide's id when it can be opened, else ""."""
    ready = ready_samples(settings)
    return ready[0] if ready else ""


def sample_cards(settings: Settings) -> list[dict[str, str]]:
    """Title and object of every ready sample, for the landing's list of guides."""
    cards = []
    for job in ready_samples(settings):
        try:
            guide = json.loads((settings.jobs_dir / job / "guide.json").read_text())
        except (OSError, ValueError):
            continue
        identity = guide.get("identity") if isinstance(guide.get("identity"), dict) else {}
        cards.append(
            {
                "id": job,
                "title": str(guide.get("title") or job),
                "object": str(identity.get("object_name") or guide.get("device") or ""),
                "steps": str(len(guide.get("steps") or [])),
            }
        )
    return cards


def is_write_to_sample(method: str, path: str, value: str) -> bool:
    """True for a change to a sample guide. The coach's own routes only read it."""
    if method in ("GET", "HEAD", "OPTIONS"):
        return False
    for job in sample_ids(value):
        if re.match(rf"^/(guides|api/jobs)/{re.escape(job)}(/|$)", path):
            return True
    return False
