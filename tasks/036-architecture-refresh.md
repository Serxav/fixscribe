# Task 036: refresh docs/ARCHITECTURE.md to the code as it is NOW
Branch: docs/architecture-v3
Owner: Muse Code (muse-spark-1.3, high)

## Goal
Your draft from task 032 is in `docs/ARCHITECTURE.md`. The code changed since: make the doc match
the code exactly. Edit ONLY `docs/ARCHITECTURE.md`. Do not run shell commands that delete or
move files.

## Check and update
- Stages: read `app/pipeline/runner.py::default_stages()` and `attempt_stages()`: 15 stages
  (proof and learn included); `app/pipeline/attempt.py` does NOT exist on main (frozen task 031):
  say "planned".
- New since your draft: `app/meta_client.make_client` / `set_client_factory` (the one switch for
  a fake Meta in tests and the offline demo), `app/spark.py::ask_json` (all strict-JSON Spark
  calls), `app/artifacts.atomic_path` (all atomic file writes), `app/text.py`,
  `app/routes/common.py` (id → folder/guide), `Settings.jobs_dir` (one jobs folder),
  runner `--resume` (restart at the failed stage; finished stages are reused, later ones rerun).
- Removed: `app/pipeline/segment.py`, `scripts/first_call.py`.
- Add a short section "Failure and recovery": optional vs required stages, what the user sees,
  `manifest.json` per-stage status, `--resume`.
- Every path, function and stage name you write must exist (check with grep / reading the code).

## Done when
- `.venv/bin/pytest -q` passes (nothing but the doc changed); `git status` shows only
  `docs/ARCHITECTURE.md` (and this task file) changed.
