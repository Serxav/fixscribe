# HANDOFF — read this when Claude Code is not available

## State (updated 2026-10-26, night)
- `main` has: skeleton, schemas, jobs, assembly, runner, guide builder, meta client (001), first-call script (002), ingest (003), eval, brief. 118 tests pass.
- Muse Code worktree is on branch `feat/transcribe`. Task 004 was launched by Claude Code; if `app/pipeline/transcribe.py` is not finished, finish 004 first.
- No real Meta call has been made by the product yet. Muse Code has spent about 0.92 $.

## Queue for Muse Code (do them in this order, one after another)
1. `tasks/004-transcribe.md`
2. `tasks/005-step-cuts.md`

## Rules for this mode
- Before each task, read `AGENTS.md` and `docs/HACKATHON_BRIEF.md`.
- Do each task exactly as written. Change only its "Files to touch".
- After each task, run `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`
  and write your report (AGENTS.md section 4, with the JURADO line) to `tasks/<id>.report.md`.
- If a task cannot be finished, write what is missing in its report and go to the next task.
- Never run git. Never open `.env`. Never call the real Meta API (tests use fakes).
- **When the queue is done, STOP.** Do nothing outside the queue, even if you see more work.
