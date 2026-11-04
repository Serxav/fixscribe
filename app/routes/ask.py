"""Live mode route: one camera frame in, the current step and next action out."""

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.limits import limit
from app.pipeline.ask import MAX_CLIP_BYTES, live_typed, live_voice
from app.pipeline.live import MAX_FRAME_BYTES, LiveError, LivePart, live_turn, marks_stages
from app.routes.common import load_guide
from app.routes.upload import settings_dep

router = APIRouter()


@router.post("/api/live/{job_id}", dependencies=[Depends(limit("coach"))])
async def live_frame(
    job_id: str,
    frame: UploadFile = File(...),  # noqa: B008
    last_step: int = Form(0),  # noqa: B008
    pending_step: int = Form(0),  # noqa: B008
    stood: int = Form(2),  # noqa: B008
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
            live_turn, folder, settings, data, last_step, None, pending_step, stood
        )
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        await frame.close()
    return JSONResponse(answer.model_dump(mode="json"))


def _marks_line(checked: bool, parts: list[LivePart]) -> str:
    return json.dumps({"checked": checked, "parts": [p.model_dump(mode="json") for p in parts]})


def _remaining_marks(stages: Iterator) -> Iterator[str]:
    try:
        for checked, parts in stages:
            yield _marks_line(checked, parts) + "\n"
    except LiveError as exc:
        yield json.dumps({"checked": True, "parts": [], "error": str(exc)}) + "\n"


@router.post("/api/live/{job_id}/marks", dependencies=[Depends(limit("coach"))])
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
        stages = marks_stages(folder, settings, data, step, box)
        checked, parts = await run_in_threadpool(next, stages)
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        await frame.close()
    first = _marks_line(checked, parts) + "\n"

    def lines() -> Iterator[str]:  # one JSON line per stage: cut out first, confirmed after
        yield first
        yield from _remaining_marks(stages)

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.post("/api/live/{job_id}/hear", dependencies=[Depends(limit("question"))])
async def live_hear(
    job_id: str,
    audio: UploadFile = File(...),  # noqa: B008
    frame: UploadFile | None = File(None),  # noqa: B008
    step: int = Form(0),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if folder is None:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if guide is None:
        return JSONResponse({"error": "guide not ready"}, status_code=404)
    try:
        clip = await audio.read(MAX_CLIP_BYTES + 1)
        picture = await frame.read(MAX_FRAME_BYTES + 1) if frame else b""
        heard = await run_in_threadpool(live_voice, folder, settings, clip, step, picture)
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        await audio.close()
        if frame:
            await frame.close()
    return JSONResponse(heard.model_dump(mode="json"))


@router.post("/api/live/{job_id}/ask", dependencies=[Depends(limit("question"))])
async def live_ask(
    job_id: str,
    text: str = Form(..., max_length=2000),  # noqa: B008
    frame: UploadFile | None = File(None),  # noqa: B008
    step: int = Form(0),  # noqa: B008
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, guide = load_guide(job_id, settings)
    if folder is None:
        return JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if guide is None:
        return JSONResponse({"error": "guide not ready"}, status_code=404)
    try:
        picture = await frame.read(MAX_FRAME_BYTES + 1) if frame else b""
        heard = await run_in_threadpool(live_typed, folder, settings, text, step, picture)
    except LiveError as exc:
        status = 429 if "live limit" in str(exc) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)
    finally:
        if frame:
            await frame.close()
    return JSONResponse(heard.model_dump(mode="json"))
