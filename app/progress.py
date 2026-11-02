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


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


SAFETY_WORDS = {
    "normal": "No special risk found",
    "caution": "Caution: warnings added",
    "professional_only": "Professional only: no instructions",
}


def stage_results(folder: Path) -> dict[str, str]:
    """One short line per finished stage, from what it wrote: "212 words", "9 cut-outs"."""
    out: dict[str, str] = {}
    ingest = _load(folder, IngestInfo)
    if ingest is not None:
        minutes, seconds = divmod(round(ingest.duration_s), 60)
        out["ingest"] = f"{minutes}:{seconds:02d} of video, {ingest.width}×{ingest.height}"
    transcript = _load(folder, Transcript)
    if transcript is not None:
        if transcript.mode == "silent":
            out["transcribe"] = "No narration: it watches only"
        else:
            words = sum(len(turn.text.split()) for turn in transcript.turns)
            out["transcribe"] = (
                f"{_plural(words, 'word')} in {_plural(len(transcript.turns), 'turn')}"
            )
    identity = _load(folder, Identity)
    if identity is not None:
        out["identify"] = f"{identity.object_name} · {identity.category}"
    analysis = _load(folder, Analysis)
    if analysis is not None:
        out["analyze"] = f"{_plural(len(analysis.steps), 'step')} drafted"
    plan = _load(folder, Plan)
    if plan is not None:
        out["plan"] = _plural(len(plan.steps), "step")
    safety = _load(folder, Safety)
    if safety is not None:
        out["safety"] = SAFETY_WORDS.get(safety.level, safety.level)
    perception = _load(folder, Perception)
    if perception is not None:
        parts = sum(1 for item in perception.steps if item.part)
        fasteners = sum(len(item.removed) for item in perception.steps)
        out["perception"] = (
            f"{_plural(parts, 'part')} cut out, {_plural(fasteners, 'fastener')} found"
        )
    guide = _load(folder, Guide)
    if guide is not None:
        back = f", {_plural(len(guide.reassembly), 'step')} back" if guide.reassembly else ""
        out["publish"] = f"{_plural(len(guide.steps), 'step')}{back}"
    return out


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
    results = stage_results(folder)
    if results:
        out["results"] = results
    return out
