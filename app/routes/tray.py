"""Print-ready A4 fastener tray page (task 030)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.routes.common import load_guide
from app.routes.upload import settings_dep, templates
from app.tray import reassembly_lines, tray_cells

router = APIRouter()


def _not_ready(request: Request, job_id: str, *, valid_id: bool):
    return templates.TemplateResponse(
        request,
        "tray.html",
        {
            "guide": None,
            "job_id": job_id,
            "valid_id": valid_id,
            "cells": [],
            "reassembly_lines": [],
        },
        status_code=404,
    )


@router.get("/guides/{job_id}/tray", response_class=HTMLResponse)
def tray_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if guide is None:
        return _not_ready(request, job_id, valid_id=folder is not None)
    return templates.TemplateResponse(
        request,
        "tray.html",
        {
            "guide": guide,
            "job_id": job_id,
            "valid_id": True,
            "cells": tray_cells(guide),
            "reassembly_lines": reassembly_lines(guide),
        },
    )
