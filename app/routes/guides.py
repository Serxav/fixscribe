"""Guide page and job media files (task 010)."""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.routes.common import job_folder, load_guide
from app.routes.upload import settings_dep, templates
from app.schemas import Guide, Perception
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
                "part": parts.get(step.index),
                "claims": [
                    {
                        "label": FIELD_LABELS.get(claim.field, claim.field),
                        "status": claim.status,
                        "sources": claim.sources,
                    }
                    for claim in claims
                ],
                "checkable": count > 0,
            }
        )
    return views


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
            "valid_id": True,
            "steps": step_views(guide, job_id, _part_boxes(folder)),
            "fasteners_total": f"{total} {plural(kind, total)}" if total else "",
            "proof_percent": round(guide.proof.score * 100) if guide.proof else None,
            "level": guide.safety.level if guide.safety else "normal",
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
