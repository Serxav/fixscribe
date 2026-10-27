# Task 030: printable fastener tray (A4)
Branch: feat/tray
Owner: Muse Code (muse-spark-1.3, high)

## Goal
`GET /guides/{job_id}/tray` returns a print-ready A4 page: one numbered cell per step that
removes fasteners, where the user drops them while working, and the reassembly order on the side.

## Why this matters for judging
A physical object that comes out of the guide: no lost screws. Demo 25 % (print it, put screws
on it), Impact 30 %.

## Files to touch
- `app/tray.py` (new): pure data, no web
- `app/routes/tray.py` (new), `app/main.py` (one include_router line)
- `web/templates/tray.html` (new, standalone: does NOT extend base.html)
- `tests/test_tray.py` (new)

## Do not touch
- `app/schemas.py`, `app/routes/guides.py`, `web/templates/guide.html`, `web/static/*`, every
  pipeline file

## What to build
`app/tray.py`:
- `@dataclass(frozen=True) class TrayCell: step: int; title: str; kind: str; count: int;
  numbers: list[int]; image: str | None` (image = step.overlay or step.image).
- `tray_cells(guide: Guide) -> list[TrayCell]`: steps with `screws.count > 0`, in step order;
  `numbers` = box numbers if present, else 1..count.
- `reassembly_lines(guide: Guide) -> list[str]`: "1. <instruction> (tray cell N)" from
  `guide.reassembly` (source_step → cell).
- Empty list when the guide has no fasteners (the page then says so).

`web/templates/tray.html`: plain HTML + inline CSS only (no Tailwind, no JS needed).
`@page { size: A4; margin: 12mm }`. Black on white, high contrast, big numbers.
Header: guide title, object (guide.identity.object_name if any), date-free.
Grid of cells (2 columns): big step number, title (1 line, ellipsis), "4 screws" with the kind
from the cell, one empty numbered circle per fastener (16 mm), small image (max 35 mm high) when
present (src = `/media/{job_id}/{image}`). Side/bottom box: reassembly order lines.
A "Print" button hidden in `@media print`. If the guide is professional-only
(`guide.safety.level == "professional_only"`), show only a box: "This job is for a qualified
professional. No tray." Footer: "FixScribe — keep each fastener in its cell."
All text in English. Cell must not split across pages (`break-inside: avoid`).

`app/routes/tray.py`: same job-id validation and 404 behaviour as `app/routes/guides.py`;
renders the template with `templates` from `app/routes/upload.py`.

## Done when
- `tests/test_tray.py`: tray_cells numbers from boxes and from count; no fastener steps skipped;
  kind "bolt" appears as "bolts"; reassembly lines map to cells; route 200 contains the step
  titles and "@page"; professional-only guide shows the no-tray message; bad id → 404.
- `.venv/bin/pytest -q` all pass, `ruff check .` and `ruff format --check .` clean.
