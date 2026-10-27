"""Job progress: JSON status API and the progress page."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import TypeAdapter

from app.config import Settings
from app.jobs import JobStatus, update_status
from app.pipeline.runner import check_stale, is_running, stage_overview, start_job
from app.routes.common import job_folder
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
    data = _status_adapter.dump_python(status)
    data["stages"] = stage_overview(status, settings.jobs_dir / job_id)
    return data


@router.post("/api/jobs/{job_id}/resume")
def api_job_resume(
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    """Try a failed job again from the stage that failed (finished stages are reused)."""
    folder = job_folder(job_id, settings)
    try:
        if folder is None:
            raise FileNotFoundError(job_id)
        status = check_stale(job_id, settings.jobs_dir)
    except (ValueError, FileNotFoundError):
        return JSONResponse({"detail": "job not found"}, status_code=404)
    if status.state != "failed" or is_running(job_id, settings.jobs_dir):
        return JSONResponse({"detail": f"job is {status.state}, not failed"}, status_code=409)
    update_status(job_id, settings.jobs_dir, state="queued", error=None, progress=0.0)
    try:
        start_job(job_id, settings.jobs_dir, resume=True)
    except OSError:
        update_status(job_id, settings.jobs_dir, state="failed", error="Could not restart the job.")
        return JSONResponse({"detail": "could not restart the job"}, status_code=500)
    return JSONResponse({"state": "queued"}, status_code=202)


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
