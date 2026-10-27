"""Home page and video upload route."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.jobs import create_job, jobs_created_today, update_status
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
    example = settings.data_dir / "example_job.txt"
    example_job = example.read_text().strip() if example.is_file() else None
    showcase = None
    if example_job:
        from app.routes.common import load_guide

        _, guide = load_guide(example_job, settings)
        if guide is not None:
            media = f"/media/{example_job}/"
            clips = [media + s.motion.clip for s in guide.steps if s.motion]
            showcase = {
                "title": guide.title,
                "object": guide.identity.object_name if guide.identity else guide.device,
                "steps": len(guide.steps),
                "proof": round(guide.proof.score * 100) if guide.proof else None,
                "clips": clips[:3],
                "poster": media + guide.steps[0].image
                if guide.steps and guide.steps[0].image
                else None,
            }
    return templates.TemplateResponse(
        request, "index.html", {"example_job": example_job, "showcase": showcase}
    )


@router.post("/upload")
async def upload_video(
    video: UploadFile,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    jobs_dir = settings.jobs_dir
    filename = video.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return HTMLResponse(
            "<h1>Unsupported video type</h1><p>Please upload a .mp4, .mov or .m4v video.</p>",
            status_code=400,
        )
    if jobs_created_today(jobs_dir) >= settings.daily_job_limit:
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
            "<h1>Video file is too big</h1>",
            status_code=413,
        )
    try:
        start_job(job_id, jobs_dir)
    except OSError:
        update_status(job_id, jobs_dir, state="failed", error="could not start the job")
        return HTMLResponse("<h1>Could not start the job, please try again.</h1>", status_code=500)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
