"""Live mode route: one camera frame in, the current step and next action out."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.pipeline.live import MAX_FRAME_BYTES, LiveError, live_turn
from app.routes.common import load_guide
from app.routes.upload import settings_dep

router = APIRouter()


@router.post("/api/live/{job_id}")
async def live_frame(
    job_id: str,
    frame: UploadFile = File(...),  # noqa: B008
    last_step: int = Form(0),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if folder is None:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if guide is None:
        return JSONResponse({"error": "guide not ready"}, status_code=404)
    try:
        data = await frame.read(MAX_FRAME_BYTES + 1)
        answer = await run_in_threadpool(live_turn, folder, settings, data, last_step)
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        await frame.close()
    return JSONResponse(answer.model_dump(mode="json"))
