# Task 034: small cleanup (no behaviour change except clearer texts)
Branch: chore/cleanup
Owner: Muse Code (muse-spark-1.3, high)

## Goal
Remove dead code and the last duplicated text rules. All existing tests keep passing (update a
test only when it checks a text this task changes on purpose).

## Files to touch
- `app/pipeline/proof.py`, `app/pipeline/stepcheck.py`, `app/pipeline/learn.py`,
  `app/pipeline/publish.py`
- delete: `app/pipeline/segment.py` (empty; SAM lives in `meta_client.segment`),
  `tests/test_first_call.py`, `scripts/first_call.py` (day-1 smoke script, replaced by
  `scripts/run_video.py`)
- tests: `tests/test_proof.py`, `tests/test_stepcheck.py`, `tests/test_learn.py`,
  `tests/test_publish.py`

## Do not touch
- KEEP these empty files: `app/pipeline/ask.py`, `app/pipeline/inspector.py`,
  `app/routes/ask.py`, `app/routes/export.py` (next features). Keep `Guide.inspector_log`.
- `app/schemas.py`, `app/text.py`, `app/meta_client.py`, `app/artifacts.py`, `runner.py`,
  `analyze.py`, `identify.py`, `refine.py`, `perception.py`, `ingest.py`, `media.py`,
  `frames.py`, `overlay.py` (another task edits them now), routes, `tests/test_pipeline_full.py`

## What to do
1. Plurals: every `f"{kind}s"` / `kind + "s"` in proof.py (~line 99) and stepcheck.py (~158)
   becomes `plural(kind)` from `app.text`; stepcheck messages use `plural(kind, n)` so "1 bolt is
   still in place." / "2 bolts are still in place." (verb agrees).
2. learn.py: use `app.text.ARTICLES` / `drop_article` instead of its own `ARTICLES`
   (normalize_term results unchanged — its tests must pass untouched).
3. publish.py: `unverified_note(kind: str) -> str` returns
   `f"The {plural(kind)} count comes from the video analysis only; it has not been verified on
   the images yet."`; keep `UNVERIFIED_SCREWS = unverified_note("screw")` (other
   tests import it) and use the guide's fastener kind when adding the note.
4. Delete the 3 files listed above. Make sure nothing imports them
   (`grep -rn "first_call\|pipeline.segment\|pipeline import.*segment" app tests scripts eval`).

## Done when
- tests: "glass" kind → "glasses" in a proof source; stepcheck message singular/plural;
  a guide with bolts gets "The bolts count comes from ..."; `UNVERIFIED_SCREWS` still exists.
- `grep -rn '}s"' app/pipeline/proof.py app/pipeline/stepcheck.py` → nothing.
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
