"""Step check route: the user posts a photo of one step, SAM answers if it is done."""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.artifacts import ArtifactError
from app.config import Settings
from app.jobs import job_dir
from app.pipeline.stepcheck import MAX_PHOTO_BYTES, CheckLimitReached, StepCheckError, check_step
from app.routes.upload import settings_dep

router = APIRouter()


@router.post("/guides/{job_id}/steps/{index}/check")
async def check_photo(
    job_id: str,
    index: int,
    photo: UploadFile = File(...),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    jobs_dir = settings.data_dir / "jobs"
    try:
        folder = job_dir(job_id, jobs_dir)
    except ValueError:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if not (folder / "guide.json").is_file():
        return JSONResponse({"error": "guide not ready"}, status_code=404)
    try:
        data = await photo.read(MAX_PHOTO_BYTES + 1)
        result = await run_in_threadpool(check_step, folder, settings, index, data)
    except StepCheckError as exc:
        status = 429 if isinstance(exc, CheckLimitReached) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    except ArtifactError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    finally:
        await photo.close()
    return result
