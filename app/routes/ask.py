"""Live mode route: one camera frame in, the current step and next action out."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app import voice
from app.config import Settings
from app.pipeline.live import MAX_FRAME_BYTES, LiveError, live_marks, live_turn
from app.routes.common import load_guide
from app.routes.upload import settings_dep

router = APIRouter()


@router.post("/api/live/{job_id}")
async def live_frame(
    job_id: str,
    frame: UploadFile = File(...),  # noqa: B008
    last_step: int = Form(0),  # noqa: B008
    pending_step: int = Form(0),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if folder is None:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if guide is None:
        return JSONResponse({"error": "guide not ready"}, status_code=404)
    try:
        data = await frame.read(MAX_FRAME_BYTES + 1)
        answer = await run_in_threadpool(
            live_turn, folder, settings, data, last_step, None, pending_step
        )
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        await frame.close()
    return JSONResponse(answer.model_dump(mode="json"))


@router.post("/api/live/{job_id}/marks")
async def live_frame_marks(
    job_id: str,
    frame: UploadFile = File(...),  # noqa: B008
    step: int = Form(0),  # noqa: B008
    region: str = Form(""),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if folder is None:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if guide is None:
        return JSONResponse({"error": "guide not ready"}, status_code=404)
    numbers = [int(n) for n in region.split(",") if n.strip().isdigit()]
    box = numbers if len(numbers) == 4 and all(n <= 1000 for n in numbers) else []
    if box and (box[0] >= box[2] or box[1] >= box[3]):
        box = []
    try:
        data = await frame.read(MAX_FRAME_BYTES + 1)
        parts = await run_in_threadpool(live_marks, folder, settings, data, step, box)
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        await frame.close()
    return JSONResponse({"parts": [part.model_dump(mode="json") for part in parts]})


@router.post("/api/voice/{job_id}")
async def spoken_line(
    job_id: str,
    text: str = Form(...),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)  # only a finished guide has lines to read
    if folder is None or guide is None:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    try:
        path = await run_in_threadpool(voice.speak, folder, settings, text)
    except voice.VoiceError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    return FileResponse(path, media_type="audio/wav")
