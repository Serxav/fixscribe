# Task 028: self-growing domain profiles (learn stage + review script)
Branch: feat/learn
Owner: Muse Code (muse-spark-1.3, high)

## Goal
After a guide is built, a deterministic `learn` stage lists the parts, fasteners and tools the
job used that its domain profile does not know yet (`profile_suggestions.json`). A script lets
a human review and apply them to `domains/<category>.json`. FixScribe gets better with every
repair, with no code change.

## Why this matters for judging
A platform that learns new vocabulary from every filmed repair: Impact 30 %, Technical depth
20 % (human-in-the-loop, validated, atomic writes).

## Files to touch
- `app/pipeline/learn.py` (new), `scripts/review_profiles.py` (new)
- `tests/test_learn.py` (new)

## Do not touch
- `app/schemas.py` (ProfileSuggestion, ProfileSuggestions exist), `app/domains.py`,
  `domains/*.json` (only the script may write them, and tests use tmp_path copies),
  `app/pipeline/runner.py`, `tests/test_pipeline_full.py`, every other stage

## What to build
`app/pipeline/learn.py`, `VERSION = "1"`, no Meta call:
- `normalize_term(text: str) -> str`: lower case, strip, collapse spaces, drop leading
  articles (a, an, the), simple singular (drop a final "s" only if the word is > 3 letters and
  does not end in "ss"). Example: "The Drain Pumps " → "drain pump".
- `suggest(guide: Guide, profile: DomainProfile) -> list[ProfileSuggestion]`:
  parts from `guide.parts`, every `step.target_part` and `step.removes`; tools from
  `guide.tools`; fastener: the step `screws.kind` values. Normalize, compare with the profile's
  normalized lists, skip known ones, skip terms shorter than 3 or longer than 40 chars, no
  duplicates; `seen_in` = "step N: <title>" or "guide tools"/"guide parts".
- `run(job_dir, settings) -> ProfileSuggestions`: needs guide.json (load with artifacts);
  category = identity category if identity.json exists and is not "other", else "generic";
  object_name from identity. Save and return.
`scripts/review_profiles.py` (argparse, plain prints, English):
- `python scripts/review_profiles.py list [--jobs data/jobs]`: every job's suggestions grouped by
  category with counts (how many jobs suggested the same term).
- `python scripts/review_profiles.py apply <job_id> [--only parts,tools] [--domains domains]
  [--jobs data/jobs]`: add that job's suggestions to the profile file, respecting the
  DomainProfile limits (parts max 20, tools max 12, fasteners max 8: skip and report what does
  not fit), validate with `DomainProfile.model_validate` before writing, write atomically
  (`app.artifacts.write_json_atomic` if it fits, else temp file + os.replace), indent 2.
  Never touch the "generic" file unless `--allow-generic`.

## Done when
- `tests/test_learn.py`: normalize_term examples; suggest skips known terms and finds a new part
  and a new tool; `run` with/without identity; script `apply` on a tmp copy of `domains/`
  adds terms, keeps the file valid, respects limits, refuses generic without the flag;
  `list` prints the counts (use `main(argv)` + capsys).
- `.venv/bin/pytest -q` all pass, `ruff check .` and `ruff format --check .` clean.
