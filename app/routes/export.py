"""Download a guide as a Markdown file (task 039)."""

from fastapi import APIRouter, Depends, Response

from app.config import Settings
from app.export import guide_markdown, slugify
from app.routes.common import load_guide
from app.routes.upload import settings_dep

router = APIRouter()


@router.get("/guides/{job_id}/export.md")
def export_markdown(
    job_id: str,
    settings: Settings = Depends(settings_dep),  # noqa: B008
):
    _, guide = load_guide(job_id, settings)
    if guide is None:
        return Response("guide not found", media_type="text/plain; charset=utf-8", status_code=404)
    return Response(
        guide_markdown(guide, job_id),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slugify(guide.title)}.md"'},
    )
