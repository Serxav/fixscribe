# HANDOFF — read this when Claude Code is not available

## State (end of day 1, 2026-10-26, late night)
- `main`: pipeline v1 (ingest → transcribe → scenes → analyze → guide → frames), web v1, audit fixes,
  visual signals stage (not wired yet), docs: ALGORITHM v2, DESIGN v2, ENGINEERING_STANDARD. 219 tests.
- Not merged: `feat/web-v2` (task 011, 8 review points) and `feat/sam-client` (task 014, unreviewed).
- `tasks/AUDIT_FOUNDATIONS.md` is the plan: foundations first (media ladder, artifacts, honest screw
  claim, signals v2, fusion, perception, eval), then web round 2 and the inspector.
- Muse Code has spent about 11.97 $ (muse-wonder-1.0 default; cap 40 $).

## Queue for Muse Code (do them in this order, one after another)
- (empty: PAUSED by Sergi until the foundations plan is approved)

## Rules for this mode
- Before each task, read `AGENTS.md` and `docs/HACKATHON_BRIEF.md`.
- Do each task exactly as written. Change only its "Files to touch".
- After each task, run `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`
  and write your report (AGENTS.md section 4, with the JURADO line) to `tasks/<id>.report.md`.
- If a task cannot be finished, write what is missing in its report and go to the next task.
- Never run git. Never open `.env`. Never call the real Meta API (tests use fakes).
- **When the queue is done, STOP.** Do nothing outside the queue, even if you see more work.
