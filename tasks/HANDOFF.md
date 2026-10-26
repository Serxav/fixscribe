# HANDOFF — read this when Claude Code is not available

## State (end of day 1, 2026-10-26)
- `main` has the whole pipeline, the audit fixes, and the web app: home, job progress and guide page (010). 201 tests pass.
- Day 2 plan: Sergi records a real repair video and runs `scripts/run_video.py` (first real Meta call), then SAM screw map, inspector, Ask, export.
- Muse Code has spent about 6.12 $ (muse-wonder-1.0 is the default model since task 009).

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
