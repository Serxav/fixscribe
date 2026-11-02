"""Guide page and job media files (task 010)."""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from app import artifacts, voice
from app.agent import loop as agent_loop
from app.agent import record as agent_record
from app.artifacts import ArtifactError
from app.config import Settings
from app.pipeline.assembly import steps_to_undo
from app.pipeline.publish import screws_verified
from app.routes.common import job_folder, load_guide
from app.routes.upload import settings_dep, templates
from app.schemas import Guide, Perception, Step, Transcript
from app.text import plural

router = APIRouter()

_MEDIA_RE = re.compile(
    r"^(video\.mp4|steps/\d{2}(_overlay)?\.jpg|steps/\d{2}(_motion|_motion_rev)?\.mp4"
    r"|steps/\d{2}_cutout\.png)$"
)


def _not_ready(request: Request, job_id: str, *, valid_id: bool):
    return templates.TemplateResponse(
        request,
        "guide.html",
        {"guide": None, "job_id": job_id, "valid_id": valid_id},
        status_code=404,
    )


MAX_PHOTO_ZOOM = 1.8  # a phone frame gets blurry past this
FOCUS_SHARE = 0.7  # the marks fill this much of the photo
MIN_QUOTE_WORDS = 3  # "Yeah." proves nothing and reads badly as a quote
FIELD_LABELS = {
    "boundaries": "When it happens",
    "instruction": "What to do",
    "fastener_count": "Fasteners",
    "part": "Which part",
}


def _mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _pct(value: float) -> float:
    return round(value * 100, 2)


def _part_boxes(folder: Path) -> dict[int, dict]:
    """The SAM part box of each step (from perception.json), for the 3D view."""
    try:
        perception = artifacts.load_optional(folder, Perception)
    except ArtifactError:
        return {}
    if perception is None:
        return {}
    return {
        item.index: {
            "label": item.part.concept,
            "x": _pct(item.part.box.x),
            "y": _pct(item.part.box.y),
            "w": _pct(item.part.box.w),
            "h": _pct(item.part.box.h),
        }
        for item in perception.steps
        if item.part is not None and item.part.box.w > 0 and item.part.box.h > 0
    }


def _cutout_part(step, media: str) -> dict | None:
    """The real shape of the part (SAM mask cut-out) for the 3D view, when motion made one."""
    motion = step.motion
    if motion is None or motion.cutout is None or motion.cutout_box is None:
        return None
    box = motion.cutout_box
    return {
        "label": motion.part,
        "x": _pct(box.x),
        "y": _pct(box.y),
        "w": _pct(box.w),
        "h": _pct(box.h),
        "cutout": media + motion.cutout,
    }


def own_words(transcript: Transcript | None, start_s: float, end_s: float) -> str:
    """What the technician said during [start_s, end_s] (their own words, for the caption)."""
    if transcript is None:
        return ""
    return " ".join(
        turn.text.strip()
        for turn in transcript.turns
        if turn.start_s < end_s and turn.end_s > start_s
    )


def film_playlist(guide: Guide, job_id: str, transcript: Transcript | None = None) -> dict:
    """Everything the film player needs: clips in both directions and the spoken lines."""
    media = f"/media/{job_id}/"
    narration = guide.narration
    lines = {line.index: line for line in narration.steps} if narration else {}
    reassembly = {item.source_step: item.instruction for item in guide.reassembly}
    steps = []
    for step in guide.steps:
        motion = step.motion
        clip = media + (motion.clip if motion else step.clip) if (motion or step.clip) else None
        reverse = media + motion.clip_reverse if motion and motion.clip_reverse else clip
        line = lines.get(step.index)
        steps.append(
            {
                "index": step.index,
                "title": step.title,
                "clip": clip,
                "reverse": reverse,
                "poster": media + step.image if step.image else None,
                "say": line.disassemble if line else step.instruction,
                "say_back": line.assemble if line else reassembly.get(step.index, step.instruction),
                # The technician's real voice is on the clip: play it instead of the device voice.
                "voice": bool(motion and motion.voice),
                "words": own_words(transcript, motion.start_s, motion.end_s) if motion else "",
                "warnings": step.warnings,
            }
        )
    return {
        "title": guide.title,
        "language": narration.language if narration else (guide.language or "en"),
        "intro": narration.intro if narration else guide.summary or guide.title,
        "outro": narration.outro_disassemble if narration else "That's it. Well done.",
        "outro_back": narration.outro_assemble if narration else "Back together. Well done.",
        "blocked": bool(guide.safety and guide.safety.level == "professional_only"),
        # Labels of the two directions: what the video shows, then the reverse.
        "forward_label": "Build" if guide.direction == "assemble" else "Take apart",
        "backward_label": "Take apart" if guide.direction == "assemble" else "Put back",
        "steps": steps,
    }


def _transcript(folder: Path) -> Transcript | None:
    try:
        return artifacts.load_optional(folder, Transcript)
    except ArtifactError:
        return None


def _focus(step: Step) -> str:
    """The zoom that brings the numbered fasteners together, as on the landing's screens.

    Only fasteners: a part's photo is already its close-up, and its box is on the whole frame.
    """
    boxes = [(b.x, b.y, b.x + b.w, b.y + b.h) for b in (step.screws.boxes if step.screws else [])]
    if not boxes:
        return ""
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    zoom = max(1.0, min(MAX_PHOTO_ZOOM, FOCUS_SHARE / max(right - left, bottom - top, 0.01)))
    # never slide past the photo's edge
    middle_x = max(0.5 / zoom, min(1 - 0.5 / zoom, (left + right) / 2))
    middle_y = max(0.5 / zoom, min(1 - 0.5 / zoom, (top + bottom) / 2))
    shift_x, shift_y = (0.5 - middle_x) * 100, (0.5 - middle_y) * 100
    return f"transform:scale({zoom:.2f}) translate({shift_x:.1f}%,{shift_y:.1f}%)"


def _quote(step: Step) -> dict | None:
    """The person's own words behind this step: the longest thing really said, if it is a phrase."""
    said = [item for item in step.evidence if item.source != "video"]
    said = [item for item in said if len(item.text.split()) >= MIN_QUOTE_WORDS]
    if not said:
        return None
    best = max(said, key=lambda item: len(item.text))
    return {"text": best.text.strip(), "at": _mmss(best.t_s)}


def _balance(guide: Guide) -> dict | None:
    """Fasteners still out at the end of the video against fasteners back; "seen" only if the
    images show every one out."""
    out = sum(
        step.screws.count for step in steps_to_undo(guide.steps, guide.direction) if step.screws
    )
    back = sum(item.screws.count for item in guide.reassembly if item.screws)
    if not out and not back:
        return None
    kinds = [step.screws.kind for step in guide.steps if step.screws and step.screws.count]
    return {
        "kind": plural(kinds[0] if kinds else "screw", 2),
        "out": out,
        "back": back,
        "even": out == back,
        "seen": screws_verified(guide.steps),
    }


def step_views(guide: Guide, job_id: str, parts: dict[int, dict]) -> list[dict]:
    """Everything the page shows for each step, computed here so the template stays simple."""
    proof = {item.index: item for item in guide.proof.steps} if guide.proof else {}
    media = f"/media/{job_id}/"
    views = []
    for step in guide.steps:
        screws = step.screws
        count = screws.count if screws else 0
        kind = screws.kind if screws else "screw"
        claims = proof[step.index].claims if step.index in proof else []
        views.append(
            {
                "step": step,
                "image": media + step.image if step.image else None,
                "overlay": media + step.overlay if step.overlay else None,
                "clip": media + step.clip if step.clip else None,
                "when": f"{_mmss(step.start_s)}–{_mmss(step.end_s)}",
                "fasteners": f"{count} {plural(kind, count)}" if count else "",
                "pins": [
                    {"n": box.number, "x": _pct(box.x + box.w / 2), "y": _pct(box.y + box.h / 2)}
                    for box in (screws.boxes if screws else [])
                ],
                "part": _cutout_part(step, media) or parts.get(step.index),
                "motion": media + step.motion.clip if step.motion else None,
                "outline": step.motion.outline if step.motion else "",
                "claims": [
                    {
                        "label": FIELD_LABELS.get(claim.field, claim.field),
                        "status": claim.status,
                        "sources": claim.sources,
                    }
                    for claim in claims
                ],
                "checkable": count > 0,
                "quote": _quote(step),
                "focus": _focus(step),
            }
        )
    return views


def found_parts(folder: Path, guide: Guide, media: str) -> dict:
    """The site's list of parts: each proven part once, with its step; the rest stay marked."""
    try:
        perception = artifacts.load_optional(folder, Perception)
    except ArtifactError:
        perception = None
    rows, seen = [], set()
    missed = 0
    hero = None
    titles = {step.index: step.title for step in guide.steps}
    for item in perception.steps if perception else []:
        if item.part is None:
            missed += 1
            continue
        hero = hero or (media + item.overlay if item.overlay else None)
        name = item.part.concept.capitalize()
        if name not in seen:
            seen.add(name)
            rows.append({"name": name, "step": item.index, "title": titles.get(item.index, "")})
    return {"rows": rows, "missed": missed, "hero": hero}


@router.get("/guides/{job_id}", response_class=HTMLResponse)
def guide_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if guide is None:
        return _not_ready(request, job_id, valid_id=folder is not None)
    total = sum(step.screws.count if step.screws else 0 for step in guide.steps)
    kinds = {step.screws.kind for step in guide.steps if step.screws and step.screws.count}
    kind = kinds.pop() if len(kinds) == 1 else "fastener"
    return templates.TemplateResponse(
        request,
        "guide.html",
        {
            "guide": guide,
            "job_id": job_id,
            "agent_on": settings.enable_inspector,
            "valid_id": True,
            "steps": step_views(guide, job_id, _part_boxes(folder)),
            "found": found_parts(folder, guide, f"/media/{job_id}/"),
            "fasteners_total": f"{total} {plural(kind, total)}" if total else "",
            "balance": _balance(guide),
            "proof_percent": round(guide.proof.score * 100) if guide.proof else None,
            "level": guide.safety.level if guide.safety else "normal",
            "agent": agent_view(folder),
            "catalog": agent_catalog(folder, job_id) if settings.enable_inspector else None,
        },
    )


AGENT_NOTES = {
    "running": ("Muse Wonder is checking this guide", "Watch it work"),
    "needs_input": ("Muse Wonder has a question for you", "Answer it"),
    "awaiting_signoff": ("Muse Wonder filed its findings", "Review and sign off"),
    "done": ("Signed off: Muse Wonder checked this guide", "See how"),
    "paused": ("Muse Wonder stopped before the end", "Open the console"),
    "failed": ("Muse Wonder stopped before the end", "Open the console"),
}


def agent_view(folder: Path) -> dict | None:
    """What the guide page says about the agent: one line and a link to its console."""
    try:
        status = agent_record.load_record(folder).status
    except (ArtifactError, ValueError, OSError):
        return None
    if agent_loop.is_running(folder):
        status = "running"
    note = AGENT_NOTES.get(status)
    if note is None:
        return None
    return {"status": status, "text": note[0], "link": note[1]}


def agent_catalog(folder: Path, job_id: str) -> dict | None:
    """The agent's parts catalog (A, B, C... each cut out by SAM), once it filed its guide."""
    try:
        record = agent_record.load_record(folder)
    except (ArtifactError, ValueError, OSError):
        return None
    if record.status not in ("awaiting_signoff", "done"):
        return None
    parts = [
        {
            "id": part.id,
            "name": part.name,
            "count": part.count,
            "image": f"/jobs/{job_id}/agent/media/{part.crop}",
        }
        for part in record.parts
        if part.verified and part.crop and (folder / "agent" / part.crop).is_file()
    ]
    if not parts:
        return None
    return {"parts": parts, "signed": record.status == "done", "steps": len(record.steps)}


@router.get("/guides/{job_id}/film", response_class=HTMLResponse)
def film_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if guide is None:
        return _not_ready(request, job_id, valid_id=folder is not None)
    return templates.TemplateResponse(
        request,
        "film.html",
        {
            "guide": guide,
            "job_id": job_id,
            "film": {
                **film_playlist(guide, job_id, _transcript(folder)),
                "meta_voice": voice.ready(
                    settings, guide.narration.language if guide.narration else guide.language
                ),
            },
        },
    )


@router.get("/guides/{job_id}/live", response_class=HTMLResponse)
def live_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if guide is None:
        return _not_ready(request, job_id, valid_id=folder is not None)
    media = f"/media/{job_id}/"
    steps = [
        {
            "index": step.index,
            "title": step.title,
            "instruction": step.instruction,
            "warnings": step.warnings,
            "photo": media + step.image if step.image else None,
        }
        for step in guide.steps
    ]
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "guide": guide,
            "job_id": job_id,
            "steps": steps,
            "meta_voice": voice.ready(settings, guide.language),
        },
    )


@router.get("/media/{job_id}/{path:path}")
def media_file(
    job_id: str,
    path: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    if not _MEDIA_RE.fullmatch(path):
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    folder = job_folder(job_id, settings)
    if folder is None:
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    target = folder / path
    if not target.is_file():
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    return FileResponse(target)
