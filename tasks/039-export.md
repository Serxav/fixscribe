# Task 039: export a guide as Markdown
Branch: feat/export
Owner: Muse Code (muse-spark-1.3, high)

## Goal
`GET /guides/{job_id}/export.md` downloads the guide as a clean, readable Markdown file
(in scope: AGENTS.md section 7 "export Markdown").

## HARD RULES
Do NOT delete, move or rename files and do NOT run git. Anything like that goes under DUDAS.

## Files to touch
- `app/export.py` (new): pure function, no web
- `app/routes/export.py` (empty today: fill it), `app/main.py` (one import + include_router line)
- `tests/test_export.py` (new)

## Do not touch
- `web/` (Claude Code is redesigning it now), `app/routes/guides.py`, `app/schemas.py`,
  every `app/pipeline/*`, every other file

## What to build
`app/export.py`: `guide_markdown(guide: Guide, job_id: str) -> str`, sections in this order:
1. `# <title>` then one line: object (identity.object_name, category) · difficulty ·
   ~N min · N steps.
2. Safety: `normal` → nothing; `caution` → "## Before you start" + prechecks as `- [ ]` items +
   reasons; `professional_only` → "## Professional only" + reasons and NO step instructions
   (the guide already hides them: print what the guide says).
3. "## Tools" and "## Parts" as bullet lists (skip empty).
4. "## Steps": per step `### N. <title>` + instruction + "Fasteners: 4 screws" (use
   `app.text.plural`, kind from `step.screws.kind`) + warnings as `> ⚠ ...` + "Video: 0:12–0:31"
   (mm:ss) + proof line "Proof: 2 verified · 1 supported · 1 unverified" from `guide.proof`.
5. "## Reassembly" numbered list; "## Automatic checks" bullets (skip empty).
6. Footer: "Made with FixScribe — Muse Spark, Muse Voice and SAM 3.1 by Meta."
No images embedded (plain text file), no HTML.

`app/routes/export.py`: router with `GET /guides/{job_id}/export.md`; use
`app.routes.common.load_guide(job_id, settings)` (bad id or no guide → 404 text); return
`Response(markdown, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition":
'attachment; filename="<slug-of-title>.md"'})`; slug = lower case a-z0-9 and dashes, max 60.

## Done when
- tests: normal guide sections; caution checklist; professional_only has no instructions;
  plural kinds (bolts, glasses); mm:ss times; proof line; route 200 with headers, 404 for bad
  id and for a job without guide.
- `.venv/bin/pytest -q` all pass, `ruff check .` and `ruff format --check .` clean.
