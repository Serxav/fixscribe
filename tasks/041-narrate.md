# Task 041: narrate stage — Spark writes the spoken script of the repair film
Branch: feat/narrate
Owner: Muse Code (muse-spark-1.3, high)

## Goal
A `narrate` stage that asks Spark (text only, no video) to write the voice-over of the repair
film: one intro, one line per step for taking apart AND one for putting back, and two outros.
Saved as `narration.json` (the `Narration` model already exists in `app/schemas.py`).
The web page speaks it with the device voice (Claude Code builds the film player).

## HARD RULES
No deleting/moving files, no git. Tests never call the real API.

## Files to touch
- `app/pipeline/narrate.py` (new), `prompts/narrate_v1.md` (new), `tests/test_narrate.py` (new)

## Do not touch
- `app/schemas.py` (Narration, NarrationLine, NARRATION_JSON_SCHEMA exist), `runner.py`,
  `publish.py`, web, every other file. Claude Code wires the stage.

## What to build (model it on app/pipeline/identify.py and app/spark.py)
- `VERSION = "1"`, `class NarrateError(Exception)`.
- Inputs: `Plan` (required), `Identity`, `Safety`, `Motion` (optional), reassembly from
  `app.pipeline.assembly.build_reassembly(plan.steps)` for the putting-back order.
- `build_prompt(plan, identity, safety, reassembly) -> str` fills `prompts/narrate_v1.md`:
  `<<LANGUAGE>>` (identity.language or "en"), `<<OBJECT>>`, `<<STEPS>>` one line per step:
  `N. <title> | <instruction> | <seconds of the step> s | fasteners: 4 screws | warnings: ...`,
  `<<REASSEMBLY>>` the putting-back instructions in order, `<<SAFETY>>` level + prechecks.
- One `ask_json(client, settings, name="film_narration", schema=NARRATION_JSON_SCHEMA,
  prompt=..., raw_path=job_dir / "narrate_raw.txt", max_output_tokens=4000)`.
- `apply_rules(plan, answer, language, safety) -> Narration` (pure, test it well):
  1. keep only step indexes that exist; one line per plan step (missing → disassemble =
     the step instruction, assemble = the matching reassembly instruction or the instruction);
  2. strip whitespace; cut each line to the number of words a voice says in the step's time:
     max(12, round(seconds × 2.6)) words, ending with "…" if cut;
  3. `professional_only` safety: every step line becomes "A qualified professional must do this
     step." in English (also the assemble line), intro = the safety reasons joined;
  4. language = identity.language or "en".
- `run(job_dir, settings, client=None) -> Narration`: build, ask, apply rules, save, return.
  Invalid JSON → NarrateError (raw file kept).

`prompts/narrate_v1.md` (English instructions; the OUTPUT must be in <<LANGUAGE>>): a calm,
clear, expert voice like a good repair video; second person; one or two short sentences per step;
name the part and the number and kind of fasteners; say the warning when there is one; the
assemble line must say the reverse action ("Put the bracket back and drive in the three
screws."); no markdown, no emojis, no step numbers inside the text; intro: what we repair and
the tools; outros: one encouraging sentence each.

## Done when
- tests: apply_rules (missing step filled, unknown index dropped, word cut with "…",
  professional_only override, language); run with a fake client: writes a loadable
  narration.json, sends `name="film_narration"`, and an invalid answer raises NarrateError.
- `.venv/bin/pytest -q` all pass; `ruff check .` and `ruff format --check .` clean.
