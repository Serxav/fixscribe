# Task 032: architecture doc v3 (universal pipeline, 15 stages, the new features)
Branch: docs/architecture-v3
Owner: Muse Code (muse-spark-1.3, high)

## Goal
`docs/ARCHITECTURE.md` describes the code as it is now on this branch, exactly. Read the code;
never describe something that is not there.

## Why this matters for judging
Technical depth 20 %: judges read this file to understand the system in 2 minutes.

## Files to touch
- `docs/ARCHITECTURE.md` only

## Do not touch
- every other file (no code changes at all)

## What to write (English, plain, max ~160 lines, same style as the current file)
1. Title "FixScribe architecture (v3: universal repair)". One paragraph: any object, identify
   first, domain profiles, rules-first safety, every claim with proof.
2. "Pieces": keep the current list, add `app/domains.py` + `domains/*.json`, `app/safety.py`,
   `app/tray.py`, `app/pipeline/stepcheck.py`, routes `checks.py` and `tray.py`.
3. "Stages (in order)": a table read from `app/pipeline/runner.py::default_stages()` — name,
   artifact it owns, optional yes/no, Meta model used (none / muse-spark-1.3 / sam-3.1 /
   muse-voice-transcribe-1.0), one-line job. Check each module to fill the model column.
   A second short table for `attempt_stages()` (attempt jobs: note `app/pipeline/attempt.py` is
   being written in task 031; say "planned" for it if the file does not exist on this branch).
4. "Domain profiles": how a category is chosen (`profile_for`), what a profile contains, how
   to add a category (one JSON file), how `learn` + `scripts/review_profiles.py` grow them.
5. "Safety": levels, `evaluate` rules (hazards + professional-only operations), `stricter`,
   what publish does for professional_only.
6. "Proof mode": claim fields, the three statuses and their exact rules (read proof.py),
   and why `Step.source_index` exists.
7. "On-demand features": step check (route, steps of the algorithm, limits), tray page.
8. Keep and update "Rules that shape the design".
9. A short "Cost per job" line list: which stages call Meta (from the modules); no invented
   numbers — only the constants you find in code/docs.

## Done when
- Every stage name, artifact and file path in the doc exists in the code (check with grep).
- `.venv/bin/pytest -q` still passes (nothing else changed).
