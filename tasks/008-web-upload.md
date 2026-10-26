# Task 008: web-upload
Branch: feat/web-upload
Owner: Muse Code

## Goal
First part of the mobile web app: a home page to record or upload a repair video, the upload
route that creates a job and starts the pipeline, and a job page with a live progress bar.

## Why this matters for judging
Impact + Demo: the judges' first contact is a technician filming a repair on a phone and watching
it turn into a guide. Recording straight from the phone camera and a progress bar that moves are
what make the live demo work.

## Files to touch
- `app/main.py`
- `app/routes/upload.py`
- `app/routes/jobs.py`
- `web/templates/base.html` (new), `web/templates/index.html` (new), `web/templates/job.html` (new)
- `web/static/job.js` (new)
- `tests/test_web_upload.py` (new)

## Do not touch
- Everything else. In particular `app/pipeline/`, `app/jobs.py`, `app/schemas.py`,
  `app/meta_client.py`, `pyproject.toml`, `.env*`.
- No new dependencies. Stack: FastAPI + Jinja2 templates + Tailwind CDN
  (`<script src="https://cdn.tailwindcss.com"></script>`) + plain JavaScript. No Streamlit, no frameworks.

## What to build

### `app/main.py`
- Keep `GET /health`. Mount `web/static` at `/static` (`StaticFiles`), include the routers from
  `app/routes/upload.py` and `app/routes/jobs.py`.
- Paths from the repo root: `ROOT = Path(__file__).resolve().parents[1]`, templates in `ROOT / "web" / "templates"`.
- A dependency `settings_dep() -> Settings` that returns `get_settings()`. Routes use
  `settings: Settings = Depends(settings_dep)` so tests can override it with
  `app.dependency_overrides[settings_dep] = lambda: Settings(model_api_key="", data_dir=tmp_path)`.
  Put `templates` and `settings_dep` in a small module the routes can import without a circular
  import (e.g. define them in `app/routes/__init__.py` is NOT allowed — use `app/main.py` only for
  the app, and put `templates` + `settings_dep` at the top of `app/routes/upload.py`; `jobs.py` imports them from there).
- Jobs folder: `settings.data_dir / "jobs"`.

### `app/routes/upload.py`
- `GET /` → `index.html`: title "FixScribe", one sentence ("Film a repair. Get a step-by-step guide."),
  a form `POST /upload` with `enctype="multipart/form-data"` and
  `<input type="file" name="video" accept="video/*" capture="environment" required>`
  (on a phone this offers the camera), a big submit button, and a short note: "Narrate with
  'step one', 'step two'… for the best cuts. Silent videos work too."
- `POST /upload` (field `video: UploadFile`):
  1. Allowed extensions (lower case): `.mp4`, `.mov`, `.m4v`. Else 400 with a friendly HTML message.
  2. If `jobs_created_today(jobs_dir) >= settings.daily_job_limit` → 429 page "Daily limit reached, try tomorrow."
  3. `create_job(jobs_dir)`, then save the upload to `<job>/original<ext>` **in chunks of 1 MB**
     (`await video.read(1024 * 1024)` in a loop). Stop and return 413 if it passes `MAX_UPLOAD_BYTES = 1024**3`
     (delete the partial file and mark the job failed with `update_status(..., state="failed", error="video file is too big")`).
  4. `start_job(job_id, jobs_dir)` (from `app.pipeline.runner`), then `RedirectResponse(f"/jobs/{job_id}", status_code=303)`.

### `app/routes/jobs.py`
- `GET /api/jobs/{job_id}` → the `JobStatus` as JSON (`read_status`). Invalid id (`ValueError`) or
  missing job (`FileNotFoundError`) → 404 JSON `{"detail": "job not found"}`.
- `GET /jobs/{job_id}` → `job.html` (404 page for a bad or missing id). Shows the job id, a progress
  bar, the current stage name and, when it fails, the error. `web/static/job.js` polls
  `/api/jobs/{id}` every 2 seconds and updates the bar (width = `progress * 100` %), the stage label
  and the state. When `state == "done"`: stop polling and show a big link "Open the guide" to
  `/guides/{id}` (that page comes in a later task). When `state == "failed"`: stop polling and show
  the error in red plus a link "Try another video" to `/`.
- Human labels for stages in `job.js`: ingest → "Preparing the video", transcribe → "Listening to the
  narration", scenes → "Finding the steps", analyze → "Watching the repair", guide → "Writing the
  guide", frames → "Picking the best photos".

### Templates
`base.html` with `<meta name="viewport" content="width=device-width, initial-scale=1">`, Tailwind CDN,
a simple header "FixScribe", and a content block. Mobile first: one column, large tap targets
(buttons at least 48 px high), readable at 360 px width. All UI text in English.

## Done when
- `.venv/bin/pytest -q` passes; `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` are clean.
- `tests/test_web_upload.py` with `TestClient`, `dependency_overrides` for settings, and
  `monkeypatch.setattr("app.routes.upload.start_job", ...)` recording the call (never start a real process):
  1. `GET /` → 200, contains `capture="environment"` and `name="video"`.
  2. `POST /upload` with a small `.mov` → 303 to `/jobs/<id>`, the file is saved as `original.mov`,
     `start_job` was called once with that id.
  3. `.txt` upload → 400, no job folder created, `start_job` not called.
  4. Daily limit 0 → 429.
  5. `MAX_UPLOAD_BYTES` monkeypatched to 10 and an 11-byte upload → 413, job state `failed`, no `original.*` left.
  6. `GET /api/jobs/<id>` → JSON with `state`; `GET /api/jobs/nothere` → 404; `GET /jobs/../etc` style id → 404.
  7. `GET /jobs/<id>` → 200 and contains `/static/job.js`.
  8. `GET /health` still returns `{"status": "ok"}`.
