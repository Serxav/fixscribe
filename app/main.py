"""FixScribe web app: health check plus upload and job-progress routes."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import guides as guides_routes
from app.routes import jobs as jobs_routes
from app.routes import upload as upload_routes

ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="FixScribe")
app.mount("/static", StaticFiles(directory=str(ROOT / "web" / "static")), name="static")
app.include_router(upload_routes.router)
app.include_router(jobs_routes.router)
app.include_router(guides_routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
