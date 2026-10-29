"""What the progress page shows while a job runs: the real findings of each finished stage.

Read-only and cheap (it only reads the job's JSON files), so the page can poll it every second
or two. Each part is present only once its stage has written it; a missing or half-written file
is simply left out, never an error.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app import artifacts
from app.schemas import (
    Analysis,
    Frames,
    Guide,
    Identity,
    IngestInfo,
    Perception,
    Plan,
    Safety,
    Transcript,
)

MAX_TURNS = 24
MAX_TURN_CHARS = 220


def _load[M: BaseModel](folder: Path, model: type[M]) -> M | None:
    try:
        return artifacts.load_optional(folder, model)
    except (artifacts.ArtifactError, ValueError, OSError):
        return None


def _short(text: str) -> str:
    """Cut a long turn at a word, with an ellipsis."""
    if len(text) <= MAX_TURN_CHARS:
        return text
    return text[:MAX_TURN_CHARS].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _steps(folder: Path, media: str) -> tuple[list[dict], bool]:
    """Steps of the plan, or Spark's draft before the plan exists, with their stills and marks."""
    plan = _load(folder, Plan)
    draft = plan is None
    source = plan or _load(folder, Analysis)
    if source is None:
        return [], draft
    frames = _load(folder, Frames)
    images = {item.index: item.image for item in frames.steps} if frames else {}
    guide = _load(folder, Guide)
    # the guide names each step's own fastener kind (pin, bolt, dowel...); the plan says "screw"
    kinds = {step.index: step.screws.kind for step in guide.steps if step.screws} if guide else {}
    perception = _load(folder, Perception)
    seen = {item.index: item for item in perception.steps} if perception else {}
    steps = []
    for number, step in enumerate(source.steps, start=1):
        index = getattr(step, "index", number)
        screws = getattr(step, "screws", None)
        found = seen.get(index)
        image = images.get(index)
        overlay = found.overlay if found else None
        steps.append(
            {
                "index": index,
                "title": step.title,
                "start_s": step.start_s,
                "end_s": step.end_s,
                "kind": kinds.get(index) or (screws.kind if screws else None),
                "count": screws.count if screws else 0,
                "image": media + image if image and (folder / image).is_file() else None,
                # the overlay is drawn on the frame where SAM found the part and the fasteners
                "overlay": media + overlay if overlay and (folder / overlay).is_file() else None,
                "part": bool(found and found.part),
                "found": len(found.removed) if found else 0,
            }
        )
    return steps, draft


def story(folder: Path, job_id: str) -> dict[str, Any]:
    """Everything the job has found so far, in the order the page reveals it."""
    media = f"/media/{job_id}/"
    out: dict[str, Any] = {}
    ingest = _load(folder, IngestInfo)
    if ingest is not None and (folder / "video.mp4").is_file():
        out["video"] = {
            "url": media + "video.mp4",
            "duration_s": ingest.duration_s,
            "width": ingest.width,
            "height": ingest.height,
        }
    identity = _load(folder, Identity)
    if identity is not None:
        out["identity"] = {
            "object": identity.object_name,
            "category": identity.category,
            "task": identity.task,
            "hazards": [hazard.replace("_", " ") for hazard in identity.hazards],
        }
    transcript = _load(folder, Transcript)
    if transcript is not None:
        out["heard"] = {
            "mode": transcript.mode,
            "turns": [
                {"t": round(turn.start_s, 1), "text": _short(turn.text)}
                for turn in transcript.turns[:MAX_TURNS]
            ],
        }
    steps, draft = _steps(folder, media)
    if steps:
        out["steps"] = steps
        out["draft"] = draft
    safety = _load(folder, Safety)
    if safety is not None:
        out["safety"] = {"level": safety.level, "reasons": safety.reasons[:3]}
    perception = _load(folder, Perception)
    if perception is not None:
        out["fasteners"] = sum(len(item.removed) for item in perception.steps)
    return out
