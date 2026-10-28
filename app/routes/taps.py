"""Tap routes: the user adds a missing fastener (SAM follows the tapped point) or removes one."""

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.artifacts import ArtifactError
from app.config import Settings
from app.meta_client import BudgetExceeded
from app.pipeline.runner import is_running
from app.pipeline.tap import TapError, add_fastener, remove_fastener
from app.routes.common import job_folder
from app.routes.upload import settings_dep
from app.schemas import Perception

router = APIRouter()


class TapPoint(BaseModel):
    x: float  # 0..1 of the step's fastener image, left to right
    y: float  # 0..1, top to bottom


def _folder_or_error(job_id: str, settings: Settings) -> tuple[Path | None, JSONResponse | None]:
    folder = job_folder(job_id, settings)
    if folder is None:
        return None, JSONResponse({"error": f"unknown job: {job_id}"}, status_code=404)
    if not (folder / "guide.json").is_file():
        return None, JSONResponse({"error": "guide not ready"}, status_code=404)
    if is_running(job_id, settings.jobs_dir):
        return None, JSONResponse({"error": "the guide is still being made"}, status_code=409)
    return folder, None


def _answer(perception: Perception, index: int) -> dict:
    step = next(item for item in perception.steps if item.index == index)
    return {"step": index, "fasteners": len(step.removed), "overlay": step.overlay}


@router.post("/guides/{job_id}/steps/{index}/fasteners")
async def tap_add(
    job_id: str,
    index: int,
    point: TapPoint,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, error = _folder_or_error(job_id, settings)
    if error is not None:
        return error
    try:
        result = await run_in_threadpool(add_fastener, folder, settings, index, point.x, point.y)
    except (TapError, BudgetExceeded) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except ArtifactError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return _answer(result, index)


@router.post("/guides/{job_id}/steps/{index}/fasteners/{number}/remove")
async def tap_remove(
    job_id: str,
    index: int,
    number: int,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder, error = _folder_or_error(job_id, settings)
    if error is not None:
        return error
    try:
        result = await run_in_threadpool(remove_fastener, folder, settings, index, number)
    except TapError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except ArtifactError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return _answer(result, index)
