# HANDOFF — read this when Claude Code is not available

## State (end of day 1, 2026-10-26)
- Backend v2 is complete on `main`: 11 stages (ingest, transcribe, signals, scenes, analyze, fusion,
  refine, plan, frames, perception, publish), typed artifacts, manifest with time and cost, per-job
  budget, evaluation runner. 328 tests pass. See `docs/ARCHITECTURE.md` and `docs/backend-diagram.html`.
- Not merged: `feat/web-v2` (task 011, 8 review points). The web waits until real data exists.
- No real Meta call yet. Muse Code has spent about 20.7 $ (muse-wonder-1.0; cap 40 $).
- Next (with Claude Code): Sergi's first real video → `scripts/run_video.py` → `eval/run_eval.py`.

## Queue for Muse Code (do them in this order, one after another)
- (empty: wait for Claude Code)

## Rules for this mode
- Before each task, read `AGENTS.md` and `docs/HACKATHON_BRIEF.md`.
- Do each task exactly as written. Change only its "Files to touch".
- After each task, run `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`
  and write your report (AGENTS.md section 4, with the JURADO line) to `tasks/<id>.report.md`.
- If a task cannot be finished, write what is missing in its report and go to the next task.
- Never run git. Never open `.env`. Never call the real Meta API (tests use fakes).
- **When the queue is done, STOP.** Do nothing outside the queue, even if you see more work.
