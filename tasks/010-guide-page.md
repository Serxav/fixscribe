# Task 010: guide-page (and one design system for every page)
Branch: feat/guide-page
Owner: Muse Code (muse-wonder-1.0)

## Goal
Build the guide page `/guides/{job_id}` — the screen the whole demo leads to — and give the three
pages (home, job progress, guide) one calm, premium, minimal design in the spirit of Apple product
pages and the Muse agent UI. A technician holding a phone with greasy fingers must be able to follow
it; a judge must think "this is a real product" in two seconds.

## Why this matters for judging
Demo (25 %) + Impact (30 %): this page is the payoff of the 3-minute video and of the live demo.
Today the "Open the guide" link is a 404 (audit finding W1). A beautiful, clear page makes every
Meta capability visible: Spark's steps and warnings, Voice's step cuts, the keyframes and loop clips.

## Before you code: design research (max 6 web pages, keep it short)
Look at a few references for layout, type and spacing, for example apple.com product and support
pages, Apple's Human Interface Guidelines (typography, layout, materials), and one well-known
step-by-step repair guide site for what technicians expect. Do not copy any code, text or images;
only take ideas. Write 5–8 bullet points of what you take from them at the top of your report
(under HECHO is fine).

## Files to touch
- `app/routes/guides.py` (new code; the file exists and is empty)
- `app/main.py` (include the guides router)
- `web/templates/base.html`, `web/templates/index.html`, `web/templates/job.html` (restyle only;
  keep every element id, form field and link the tests and `job.js` rely on)
- `web/templates/guide.html` (new), `web/static/guide.js` (new), `web/static/app.css` (new, optional)
- `web/static/job.js` (only if the new job page design needs it)
- `tests/test_web_guides.py` (new)

## Do not touch
- `app/pipeline/`, `app/jobs.py`, `app/schemas.py`, `app/meta_client.py`, `app/routes/upload.py`,
  `app/routes/jobs.py`, `pyproject.toml`, `.env*`. No new dependencies.
- Stack stays FastAPI + Jinja2 + Tailwind CDN + plain JavaScript (no frameworks, no build step,
  no external images or icon fonts: draw icons as small inline SVGs).

## Design system (follow it; small refinements are welcome if you explain them)
- **Type:** `font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, system-ui, sans-serif`.
  Title 34/40 px semibold with slight negative tracking; section titles 22 px semibold; body 17 px;
  secondary 15 px; captions 13 px. Numbers in steps use tabular figures.
- **Colors (light):** page `#F5F5F7`, cards `#FFFFFF`, text `#1D1D1F`, secondary `#6E6E73`,
  hairlines `rgba(0,0,0,.08)`, one accent `#0071E3`, success `#1E8E3E`, warning text `#B25000` on `#FFF4E5`.
  **Dark mode** with `prefers-color-scheme: dark`: page `#000000`, cards `#1C1C1E`, text `#F5F5F7`,
  secondary `#98989D`, accent `#2997FF`, warning on `#3A2A12`.
- **Shape and space:** cards with 22 px radius and a very soft shadow (or hairline in dark mode),
  pills fully rounded, 16 px side gutters on phones, content max width 680 px centered on large
  screens, generous vertical rhythm (24–32 px between blocks).
- **Touch:** every tap target at least 48 px high. Visible focus rings. `prefers-reduced-motion` respected.
- **Motion:** only subtle: cards fade-and-rise 8 px when they enter the viewport; the segmented control slides.
- **Tone:** no emojis, short labels, sentence case.

## The guide page `/guides/{job_id}`
Data: read `data/jobs/<id>/guide.json` with `Guide.model_validate_json` (jobs folder =
`settings.data_dir / "jobs"`, use `settings_dep` and `templates` from `app/routes/upload.py`).
1. **Header:** small wordmark "FixScribe" (links to `/`).
2. **Hero:** device as a small uppercase eyebrow, the guide title, the summary, and a row of pills:
   difficulty, `~N min` (if > 0), `N steps`, `N screws` (sum of step screw counts, if > 0).
   Tools as a horizontal row of chips (scrolls sideways on small screens, no page overflow).
3. **Safety card** (only if `guide.warnings`): amber card with a warning icon and the warnings.
4. **Segmented control** "Take apart" / "Put back" switching between two views without a reload.
5. **Take apart view:** one card per step:
   - media: the step clip (`step.clip`) as `<video muted loop playsinline preload="metadata" poster="<image>">`,
     playing only while the card is on screen (IntersectionObserver), with the keyframe image as
     poster; if there is no clip, show the image; if neither, a neutral placeholder with the step number.
   - big step number ("01"), title, instruction.
   - chips: the action (e.g. "Unscrew") and `N screws` if any.
   - step warnings as amber rows with an icon.
   - a "Check this step" badge when `step.review == "needs_review"`.
   - a **"Watch in video"** pill button with `data-start` / `data-end`: opens a bottom sheet with the
     full `video.mp4`, seeks to `start_s`, plays, and pauses at `end_s`. Close button and Escape key.
6. **Put back view:** the screw check card first: if no item in `guide.checks` contains "screw",
   a green check "Every screw goes back" with the total; otherwise an amber card listing those checks.
   Then one row per `guide.reassembly` step: number, `action` + parts (e.g. "Screw in · back cover"),
   and screw info `N screws · positions 1–4` when the step has screws with boxes.
   Other `guide.checks` (not about screws) go in a small "Notes" list at the end.
7. **Footer:** "Made with FixScribe — Muse Spark, Muse Voice and SAM 3.1 by Meta."
8. Not ready / missing: unknown id, bad id, or no `guide.json` yet → 404 page in the same design:
   "This guide is not ready yet." with a link to `/jobs/{id}` (only when the id is valid).

### Media route
`GET /media/{job_id}/{path:path}` → `FileResponse` for exactly these paths: `video.mp4`,
`steps/NN.jpg`, `steps/NN.mp4` (regex `^(video\.mp4|steps/\d{2}\.(jpg|mp4))$`). Anything else, a bad
id or a missing file → 404. Validate the id with `job_dir()` from `app/jobs.py`. (Starlette's
`FileResponse` supports HTTP range requests, which iPhone Safari needs for video.)
In the templates, build media URLs as `/media/{job_id}/{step.image}` etc.

### Restyle home and job pages with the same system
- Home: big hero "Film a repair." / "Get a step-by-step guide." with one large rounded primary
  button for the file input (keep `name="video"`, `accept="video/*"`, `capture="environment"`),
  and three small quiet lines explaining narrated vs silent videos.
- Job page: a calm card with the stage label, a slim progress bar, and the list of stages with a
  check mark for the finished ones and a soft pulse on the current one (labels from `job.js`).
  Keep the ids `job.js` uses.

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- `tests/test_web_guides.py` (build `guide.json` with the `Guide`/`Step`/`ScrewMap`/`Box`/`ReassemblyStep`
  models, write tiny fake files for `steps/01.jpg`, `steps/01.mp4`, `video.mp4`):
  1. `GET /guides/<id>` → 200 and contains the title, "Take apart", "Put back", "Watch in video",
     `data-start="`, `/media/<id>/steps/01.mp4` and the step warning text.
  2. Guide with a "Screw check: 6 screws removed, 4 put back." check → the amber screw card text is
     shown; a guide with no screw checks → "Every screw goes back".
  3. `needs_review` step → "Check this step".
  4. Missing `guide.json` → 404 with "not ready" and a link to `/jobs/<id>`; bad id → 404.
  5. `GET /media/<id>/steps/01.jpg` → 200; `GET /media/<id>/guide.json` → 404;
     `GET /media/<id>/../status.json` style paths → 404; `GET /media/<id>/steps/99.jpg` (missing) → 404.
  6. Existing tests for `/`, `/upload` and `/jobs/<id>` still pass unchanged.
- Report the design decisions (5–8 bullets) and anything you could not do.
