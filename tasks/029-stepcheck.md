# Task 029: step check ("ghost camera" backend): is this step done on my object?
Branch: feat/stepcheck
Owner: Muse Code (muse-spark-1.3, high)

## Goal
The user does step N of a guide on their own object, takes a photo, and FixScribe answers
"done" / "2 bolts are still in place" / "unclear", using the same SAM + ORB alignment the
perception stage already uses. Backend + JSON route only (the camera UI comes later).

## Why this matters for judging
A guide that checks your work with SAM 3.1 on your own photo: Use of Meta AI 25 %, Impact 30 %,
Demo 25 % (a live "2 bolts left" moment).

## Files to touch
- `app/pipeline/stepcheck.py` (new)
- `app/pipeline/perception.py`: ONLY rename `_screws_on_still` → `fasteners_on_still` and
  `_roi_norm` → `roi_of` (public, same behaviour; update the call sites in this file). Nothing else.
- `app/routes/checks.py` (new), `app/main.py` (one `include_router` line)
- `tests/test_stepcheck.py` (new), `tests/test_perception.py` only if a renamed name is used there

## Do not touch
- `app/schemas.py` (StepCheck exists), `app/meta_client.py`, `app/pipeline/runner.py`,
  every other file

## What to build
`app/pipeline/stepcheck.py`:
- `MAX_PHOTO_BYTES = 15 * 1024**2`, `MAX_CHECKS_PER_JOB = 20`, `class StepCheckError(Exception)`.
- `load_photo(data: bytes) -> np.ndarray`: Pillow open, `ImageOps.exif_transpose` (phones store
  rotation in EXIF), convert RGB → BGR array. Reject > MAX_PHOTO_BYTES or unreadable with
  StepCheckError (clear message).
- `reference_still(job_dir, guide, step) -> Path`: the still just after the step
  (`step.end_s + perception.AFTER_S`, clamped to the video), extracted once from the original
  with `media.extract_still` into `checks/ref_NN.png` (reuse if it exists). Needs ingest.json
  source; else StepCheckError.
- `check_step(job_dir: Path, settings, step_index: int, photo: bytes, client=None) -> StepCheck`:
  1. Load `Guide` (guide.json) and `Perception` (optional). Unknown step → StepCheckError.
  2. Count existing `checks/step_*.json`; >= MAX_CHECKS_PER_JOB → StepCheckError("check limit").
  3. kind = `step.screws.kind` if the step has a screw map else `perception.fastener_concept(job_dir)`.
  4. If the step removes no fasteners (`not step.screws or step.screws.count == 0`): verdict
     "unclear", message "This step has no fasteners to check. Compare your photo with the guide
     image.", no SAM call.
  5. Align the photo to the reference with `align_after_to_before(reference_img, photo_img)`;
     if it works, warp the photo into the reference frame (`cv2.warpAffine`) and `aligned=True`.
  6. ROI = `roi_of(step_perception.part)` (whole image if none). Count fasteners with
     `fasteners_on_still(client, sp, photo_path, roi, image=warped_or_photo, fastener=kind)`
     (write the photo PNG into `checks/` first; `sp` = a throwaway StepPerception to count calls).
  7. expected_left = `step_perception.screws_after` if perception has the step, else None.
  8. Verdict: expected_left is None or not aligned → "unclear" with a message that still says what
     SAM found ("SAM found 3 bolts; the photo could not be matched to the guide."). Else found <=
     expected_left → "done" ("No bolts left where the guide removes them."); found > expected_left
     → "not_yet" ("2 bolts are still in place."). Boxes = found boxes.
  9. Save the result as `checks/step_NN_<k>.json` (k = 1, 2, ... next free number) atomically with
     `artifacts.write_json_atomic`; return it.
- Every SAM call goes through `MetaClient(settings, job_dir=job_dir)` (spend counted on the job);
  `BudgetExceeded` → StepCheckError("budget reached").

`app/routes/checks.py`:
- `POST /guides/{job_id}/steps/{index}/check` (multipart field `photo`): read at most
  MAX_PHOTO_BYTES + 1 bytes, call `check_step`, return the StepCheck as JSON. Errors:
  bad job id / no guide → 404; StepCheckError → 400 with `{"error": message}`, "check limit" → 429.
  Validate job ids the same way `app/routes/guides.py` does. Run the check in a threadpool
  (`starlette.concurrency.run_in_threadpool`) so the server stays responsive.

## Done when
- `tests/test_stepcheck.py` (fake client, no network; build stills with numpy/cv2, a guide.json and
  perception.json by hand in tmp_path, monkeypatch `reference_still` if simpler):
  done / not_yet / unclear (no alignment) / no-fastener step (zero SAM calls) / unknown step /
  too-large photo / limit reached / EXIF-rotated JPEG is turned upright; route returns 200 JSON,
  400 and 429 via TestClient.
- `.venv/bin/pytest -q` all pass, `ruff check .` and `ruff format --check .` clean.
