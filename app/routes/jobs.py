"""Job progress: JSON status API and the progress page."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import TypeAdapter

from app.config import Settings
from app.jobs import JobStatus
from app.pipeline.runner import check_stale
from app.routes.upload import settings_dep, templates

router = APIRouter()
_status_adapter = TypeAdapter(JobStatus)


@router.get("/api/jobs/{job_id}")
def api_job_status(
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    try:
        status = check_stale(job_id, settings.jobs_dir)
    except (ValueError, FileNotFoundError):
        return JSONResponse({"detail": "job not found"}, status_code=404)
    return _status_adapter.dump_python(status)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    try:
        status = check_stale(job_id, settings.jobs_dir)
    except (ValueError, FileNotFoundError):
        return HTMLResponse("<h1>job not found</h1>", status_code=404)
    return templates.TemplateResponse(request, "job.html", {"job_id": job_id, "status": status})
