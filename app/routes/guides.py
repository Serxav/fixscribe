"""Guide page and job media files (task 010)."""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.config import Settings
from app.routes.common import job_folder, load_guide
from app.routes.upload import settings_dep, templates

router = APIRouter()

_MEDIA_RE = re.compile(r"^(video\.mp4|steps/\d{2}(_overlay)?\.jpg|steps/\d{2}\.mp4)$")


def _not_ready(request: Request, job_id: str, *, valid_id: bool):
    return templates.TemplateResponse(
        request,
        "guide.html",
        {"guide": None, "job_id": job_id, "valid_id": valid_id},
        status_code=404,
    )


def _screw_info(step) -> str:
    screws = step.screws
    if not screws or not screws.boxes:
        return ""
    numbers = sorted(box.number for box in screws.boxes)
    if len(numbers) == 1:
        positions = f"position {numbers[0]}"
    else:
        positions = f"positions {numbers[0]}–{numbers[-1]}"
    return f"{screws.count} screws · {positions}"


@router.get("/guides/{job_id}", response_class=HTMLResponse)
def guide_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if guide is None:
        return _not_ready(request, job_id, valid_id=folder is not None)
    total_screws = sum(step.screws.count if step.screws else 0 for step in guide.steps)
    screw_checks = [check for check in guide.checks if "screw" in check.lower()]
    other_checks = [check for check in guide.checks if "screw" not in check.lower()]
    reassembly_rows = [{"step": item, "screw_info": _screw_info(item)} for item in guide.reassembly]
    return templates.TemplateResponse(
        request,
        "guide.html",
        {
            "guide": guide,
            "job_id": job_id,
            "valid_id": True,
            "total_screws": total_screws,
            "screw_checks": screw_checks,
            "other_checks": other_checks,
            "reassembly_rows": reassembly_rows,
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
