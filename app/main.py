"""FixScribe web app: health check plus upload and job-progress routes."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import demo
from app.config import get_settings
from app.routes import ask as ask_routes
from app.routes import checks as checks_routes
from app.routes import console as console_routes
from app.routes import export as export_routes
from app.routes import guides as guides_routes
from app.routes import jobs as jobs_routes
from app.routes import taps as taps_routes
from app.routes import tray as tray_routes
from app.routes import upload as upload_routes

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    demo.seed(get_settings())
    yield


app = FastAPI(title="FixScribe", lifespan=lifespan)


@app.middleware("http")
async def sample_guide_is_read_only(request: Request, call_next):
    if demo.is_write_to_sample(request.method, request.scope["path"], get_settings().demo_job):
        return JSONResponse({"error": "The sample guide cannot be changed."}, status_code=403)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(ROOT / "web" / "static")), name="static")
app.include_router(upload_routes.router)
app.include_router(jobs_routes.router)
app.include_router(guides_routes.router)
app.include_router(export_routes.router)
app.include_router(checks_routes.router)
app.include_router(taps_routes.router)
app.include_router(ask_routes.router)
app.include_router(tray_routes.router)
app.include_router(console_routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
