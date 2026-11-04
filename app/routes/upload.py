"""Home page and video upload route."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import demo
from app.config import Settings, get_settings
from app.jobs import claim_daily_slot, create_job, update_status
from app.limits import limit
from app.pipeline.runner import start_job

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "web" / "templates"))

MAX_UPLOAD_BYTES = 1024**3
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v"}
CHUNK_BYTES = 1024 * 1024


def settings_dep() -> Settings:
    """Return process settings. Tests override this with a tmp data_dir."""
    return get_settings()


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request, settings: Settings = Depends(settings_dep)):  # noqa: B008
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sample": demo.ready_sample(settings),
            "samples": demo.sample_cards(settings),
            "uploads": settings.uploads,
            "max_minutes": max(1, settings.max_video_seconds // 60),
        },
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})


@router.post("/upload", dependencies=[Depends(limit("video"))])
async def upload_video(
    video: UploadFile,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    if not settings.uploads:
        return HTMLResponse(
            "<h1>This demo server does not make new guides</h1><p>It is too small to process "
            "video. Open the sample guide and its live coach from the home page, or run "
            "FixScribe on your own computer.</p>",
            status_code=503,
        )
    jobs_dir = settings.jobs_dir
    filename = video.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return HTMLResponse(
            "<h1>Unsupported video type</h1><p>Please upload a .mp4, .mov or .m4v video.</p>",
            status_code=400,
        )
    if not settings.model_api_key:
        # Without a key every job would fail minutes later with a library's message.
        return HTMLResponse(
            "<h1>Guides are not set up on this server</h1><p>It has no Meta key yet.</p>",
            status_code=503,
        )
    if not claim_daily_slot(jobs_dir, settings.daily_job_limit):
        return HTMLResponse(
            "<h1>Daily limit reached, try tomorrow.</h1>",
            status_code=429,
        )
    status = create_job(jobs_dir)
    job_id = status.job_id
    dest = jobs_dir / job_id / f"original{ext}"
    size = 0
    too_big = False
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await video.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    too_big = True
                    break
                out.write(chunk)
    except Exception:
        # Upload cut (phone lost signal) or disk error: never leave a job "queued" forever.
        dest.unlink(missing_ok=True)
        update_status(job_id, jobs_dir, state="failed", error="the upload was interrupted")
        raise
    finally:
        await video.close()
    if too_big:
        dest.unlink(missing_ok=True)
        update_status(job_id, jobs_dir, state="failed", error="video file is too big")
        return HTMLResponse(
            "<h1>Video file is too big</h1><p>The limit is 1 GB: film in 1080p, or a shorter"
            " video.</p>",
            status_code=413,
        )
    try:
        start_job(job_id, jobs_dir)
    except OSError:
        update_status(job_id, jobs_dir, state="failed", error="could not start the job")
        return HTMLResponse("<h1>Could not start the job, please try again.</h1>", status_code=500)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
