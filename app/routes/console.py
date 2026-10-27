"""Agent Console: watch the agent work turn by turn, answer it, sign off (task 047)."""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import artifacts
from app.agent import loop
from app.agent import record as record_mod
from app.agent.record import SignOff
from app.config import Settings
from app.routes.common import job_folder
from app.routes.upload import settings_dep, templates
from app.schemas import Guide

router = APIRouter()

_MEDIA_RE = re.compile(r"(frames|crops)/[A-Za-z0-9_.-]+\.(jpg|jpeg|png)")


def _folder_or_none(job_id: str, settings: Settings):
    folder = job_folder(job_id, settings)
    if folder is None or not folder.is_dir():
        return None
    return folder


def _page_404() -> HTMLResponse:
    return HTMLResponse("<h1>job not found</h1>", status_code=404)


def _api_404() -> JSONResponse:
    return JSONResponse({"detail": "job not found"}, status_code=404)


def _start_result(folder) -> JSONResponse:
    try:
        started = loop.launch(folder, resume=False)
    except NotImplementedError:
        return JSONResponse({"error": "The agent is not ready yet."}, status_code=501)
    return JSONResponse({"started": bool(started)})


def _resume_result(folder) -> JSONResponse:
    try:
        started = loop.launch(folder, resume=True)
    except NotImplementedError:
        return JSONResponse({"error": "The agent is not ready yet."}, status_code=501)
    return JSONResponse({"started": bool(started)})


@router.get("/jobs/{job_id}/console", response_class=HTMLResponse)
def console_page(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return _page_404()
    title = "Agent run"
    try:
        guide = artifacts.load_optional(folder, Guide)
    except Exception:
        guide = None
    if guide is not None and guide.title:
        title = guide.title
    return templates.TemplateResponse(request, "console.html", {"job_id": job_id, "title": title})


@router.get("/api/jobs/{job_id}/agent")
def api_agent_state(
    job_id: str,
    after: int = 0,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return _api_404()
    rec = record_mod.load_record(folder)
    turns = record_mod.load_turns(folder, after=after)
    return JSONResponse(
        {
            "record": rec.model_dump(mode="json"),
            "turns": [turn.model_dump(mode="json") for turn in turns],
        }
    )


@router.post("/api/jobs/{job_id}/agent/start")
def api_agent_start(
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return _api_404()
    return _start_result(folder)


@router.post("/api/jobs/{job_id}/agent/resume")
def api_agent_resume(
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return _api_404()
    return _resume_result(folder)


@router.post("/api/jobs/{job_id}/agent/answer")
async def api_agent_answer(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return _api_404()
    try:
        body = await request.json()
    except Exception:
        body = None
    answer = body.get("answer") if isinstance(body, dict) else None
    if not isinstance(answer, str) or not 1 <= len(answer) <= 500 or not answer.strip():
        return JSONResponse({"error": "answer must be 1..500 characters"}, status_code=400)
    rec = record_mod.load_record(folder)
    if rec.status != "needs_input":
        return JSONResponse({"detail": f"agent is {rec.status}, not needs_input"}, status_code=409)
    record_mod.write_answer(folder, answer)
    try:
        loop.launch(folder, resume=True)
    except NotImplementedError:
        return JSONResponse({"error": "The agent is not ready yet."}, status_code=501)
    return JSONResponse({"ok": True})


@router.post("/api/jobs/{job_id}/agent/signoff")
async def api_agent_signoff(
    request: Request,
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return _api_404()
    try:
        body = await request.json()
    except Exception:
        body = None
    approved = body.get("approved") if isinstance(body, dict) else None
    notes = body.get("notes", "") if isinstance(body, dict) else None
    if not isinstance(approved, bool) or not isinstance(notes, str):
        return JSONResponse({"error": "approved and notes are required"}, status_code=400)
    if not approved and not notes.strip():
        return JSONResponse({"error": "notes are required to request changes"}, status_code=400)
    rec = record_mod.load_record(folder)
    if rec.status != "awaiting_signoff":
        return JSONResponse(
            {"detail": f"agent is {rec.status}, not awaiting_signoff"}, status_code=409
        )
    record_mod.write_signoff(folder, SignOff(approved=approved, notes=notes))
    try:
        loop.launch(folder, resume=True)
    except NotImplementedError:
        return JSONResponse({"error": "The agent is not ready yet."}, status_code=501)
    return JSONResponse({"ok": True})


@router.get("/jobs/{job_id}/agent/media/{path:path}")
def agent_media(
    job_id: str,
    path: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    if not _MEDIA_RE.fullmatch(path):
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    folder = _folder_or_none(job_id, settings)
    if folder is None:
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    target = folder / "agent" / path
    if not target.is_file():
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    return FileResponse(target)
