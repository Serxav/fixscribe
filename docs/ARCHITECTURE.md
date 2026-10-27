# FixScribe architecture (v3: universal repair)

A phone video of any repair goes in; a verified step-by-step guide comes out. The pipeline
first identifies what it is looking at (object, category, task, hazards, language), then picks
a domain profile for that category (`domains/<category>.json`), so a new category is one JSON
file, never new code. Safety is rules first (`app/safety.py`): professional-only jobs get no
instructions, and a model may only raise the level, never lower it. Every claim of the guide
carries its proof: each step's boundaries, instruction, fastener count and part are graded
verified / supported / unverified with the video seconds, spoken words and SAM measurements
behind them (`proof.json`).

## Pieces

| Piece | Code | Job |
|---|---|---|
| Web app | `app/main.py`, `app/routes/` | upload, progress API, guide page, media files, tray page, step checks |
| Job store | `app/jobs.py` | one folder per job under `Settings.jobs_dir` (`data/jobs/<id>/`), `status.json` (locked, atomic), stale-job detection |
| Runner | `app/pipeline/runner.py` | one process per job, stages in order, `manifest.json` (version, seconds, dollars per stage), `--resume` restarts at the failed stage |
| Artifacts | `app/schemas.py`, `app/artifacts.py` (`atomic_path`) | one Pydantic model per file; artifact and media files are written atomically (`write_json_atomic`, `atomic_path`: temp file in the same folder, then rename) |
| Spark JSON | `app/spark.py` (`ask_json`) | the one strict-JSON Spark call shared by analyze, identify and refine (prompt plus images or an uploaded video; raw answer saved; `SparkAnswerError` on bad JSON) |
| Text | `app/text.py` (`plural`, `drop_article`) | small English helpers shared by the stages, kept in one place |
| Route helpers | `app/routes/common.py` (`job_folder`, `load_guide`) | URL id → job folder and guide, in one place |
| Meta door | `app/meta_client.py` (`make_client`, `set_client_factory`) | the only code that talks to Meta: Spark, Voice, SAM; retries, global and per-job budget, spend log; pipeline code gets its client only via `make_client`, and tests and the offline demo swap in a fake with `set_client_factory` |
| Domains | `app/domains.py`, `domains/*.json` | one validated profile per category: fasteners, parts, tools, prechecks, hazards |
| Safety rules | `app/safety.py` | fixed levels and regex rules; `evaluate`, `stricter` (models may only raise) |
| Tray data | `app/tray.py` | printable fastener-tray cells + reassembly lines from a guide (pure data, no web) |
| Step check | `app/pipeline/stepcheck.py` | "ghost camera": a user photo answered done / not_yet / unclear via SAM |
| Routes | `app/routes/checks.py`, `app/routes/tray.py` | `POST /guides/{id}/steps/{n}/check`, `GET /guides/{id}/tray` |
| Evaluation | `eval/score.py`, `eval/run_eval.py` | labelled videos → step F1, boundaries, screws, seconds, dollars |

## Stages (in order)

From `default_stages()` in `app/pipeline/runner.py`. Optional stages warn and continue on
failure; required stages fail the job. A stage's owned artifact is deleted before it runs.

| # | Stage | Owns | Optional | Model | Job |
|---|---|---|---|---|---|
| 1 | ingest | `ingest.json` | no | none | normalize upload: CFR proxy `video.mp4` + `audio.wav`, keep the original |
| 2 | transcribe | `transcript.json` | yes | voice | WAV to timestamped turns (keywords step/paso); silent when no audio |
| 3 | identify | `identity.json` | yes | spark | 4 stills + first words → object, category, hazards, language |
| 4 | signals | `signals.json` | yes | none | motion + scene-change signals from the proxy (OpenCV) |
| 5 | scenes | `scenes.json` | no | none | spoken "step"/"paso" turns → step segments |
| 6 | analyze | `analysis.json` | no | spark | full video + transcript + domain hint → draft steps |
| 7 | fusion | `fusion.json` | yes | none | snap Spark times to voice/visual candidates |
| 8 | refine | `refine.json` | yes | spark | timecode-burned clips re-read the uncertain steps |
| 9 | plan | `plan.json` | no | none | final steps and times; every change logged in checks |
| 10 | safety | `safety.json` | no | none | rules-only `evaluate` over plan + speech + domain hazards |
| 11 | frames | `frames.json` | yes | none | sharpest keyframe, step still/clip (`stills/`, `steps/`) |
| 12 | perception | `perception.json` | yes | sam | part highlight + before/after fastener ledger and overlay |
| 13 | proof | `proof.json` | yes | none | every claim graded with its sources |
| 14 | publish | `guide.json` | no | none | plan + media + perception + reassembly; pro-only redaction |
| 15 | learn | `profile_suggestions.json` | yes | none | new vocabulary the profile does not know yet |

Attempt jobs (`attempt_stages()` in `app/pipeline/runner.py`: a user's own repair video vs a reference guide):

| # | Stage | Owns | Optional | Model | Job |
|---|---|---|---|---|---|
| 1 | ingest | `ingest.json` | no | none | same normalize as above |
| 2 | transcribe | `transcript.json` | yes | voice | same transcription as above |
| 3 | attempt | `attempt_review.json` | no | planned | planned (`app/pipeline/attempt.py` does not exist on this branch) |

## Domain profiles

`profile_for(category)` picks the profile: exact category match, else the `generic` fallback
(`"other"` and unknown names also fall back; it never raises). A profile holds `category`,
`label`, `fasteners` (2–8 lowercase nouns), `fastener_kind`, `parts` (5–20), `tools` (3–12),
`prechecks`, `default_hazards` (must be known `HAZARDS` names) and `prompt_hint`, which steers
the analyze prompt. Eight profiles ship: appliance, automotive, electrical, electronics,
furniture, plumbing, tools, generic. A new category is one file `domains/<category>.json`
(`category` must equal the file stem; `DomainProfile` rejects the rest). The `learn` stage
only suggests (`profile_suggestions.json`); `scripts/review_profiles.py list` groups suggestions
by category with counts, and `apply <job_id>` merges them into the profile (caps: parts 20,
tools 12, fasteners 8; refuses `generic` without `--allow-generic`).

## Safety

Levels: `normal`, `caution`, `professional_only`. `evaluate(identity, texts, prechecks)` is
rules-only: any identity hazard in `PRO_HAZARDS` (gas, refrigerant, airbag,
high_voltage_battery) or any `PRO_RULES` regex hit (gas line, electrical panel, airbag,
refrigerant, high-voltage battery, microwave capacitor/magnetron/transformer with microwave
context) → `professional_only` with the rule reason and the operation in `blocked`; any other
hazard → `caution`. The domain `prechecks` are always kept. `stricter(current, proposed)` takes
the higher level and unions reasons, prechecks and blocked — the only way a model opinion
enters, so it can never lower the rules. For `professional_only`, publish replaces every
instruction with the pro-only sentence, empties the reassembly, and appends
`Professional-only job: <reasons>` to `guide.checks`.

## Proof mode

Each step gets claims (`Claim.field`): `boundaries` and `instruction` always, `fastener_count`
only when the step removes fasteners, `part` only when it names a target part. Statuses:
`verified` (two independent sources agree, or a measurement confirms), `supported` (one source),
`unverified` (nothing backs it). Exact rules: boundaries is verified with a non-Spark signal
(voice/pause/scene) plus a timecode re-check (confidence ≥ 0.7), supported with either one;
instruction is verified with video and voice evidence, supported with any source; fastener
count is verified when SAM ran and removed == claimed, supported when SAM removed some but a
different number or the re-check agrees; part is verified at SAM confidence ≥ 0.5, supported
when found with lower or unknown confidence. Scores: verified 1, supported 0.5, unverified 0;
step score is the claim mean, `proof.score` the step mean. `Step.source_index` exists because
fusion and refine key steps by Spark's draft numbers (1, 2, 3… in time order) while the plan
may drop or reorder steps: proof joins fusion/refine on `source_index` and perception on
`index`.

## On-demand features

Step check (`POST /guides/{job_id}/steps/{index}/check` → `check_step`): 1) load the guide and
enforce the per-job check limit; 2) decode the photo (≤ 15 MB, EXIF-uprighted); 3) extract the
guide still just after the step (`end_s` + 0.5 s) from the original video; 4) align the photo
to that still; 5) count fasteners with SAM in the part region (same helpers as perception);
6) verdict: no fasteners → `unclear`; no expected count or not aligned → `unclear`; found ≤
expected left → `done`; else `not_yet`. Each answer is saved as `checks/step_NN_<k>.json`.
Limits: `MAX_PHOTO_BYTES` 15 MB, `MAX_CHECKS_PER_JOB` 20 per job (further photos get 429).
Tray page (`GET /guides/{job_id}/tray`): a print-ready A4 sheet with one cell per step that
removes fasteners (step, title, kind, count, numbers, image) plus reassembly lines naming the
tray cell each line draws its fasteners from.

## Failure and recovery

Required stages (ingest, scenes, analyze, plan, safety, publish) fail the job when they
fail; optional stages (transcribe, identify, signals, fusion, refine, frames, perception,
proof, learn) add a short warning to `status.json` and the job continues without them. A
stage's owned artifact is deleted before it runs, so a retry never reads a stale result.

What the user sees: the progress bar (stage weights in `default_stages()`), the current
stage name, and on failure one human sentence (the stage name plus the error, capped at
300 chars by `short_error`), never a traceback. A job stuck in `queued` or `running`
whose runner died is marked failed by `check_stale` ("The job stopped unexpectedly.
Please try again.").

`manifest.json` records one `StageRecord` per stage that ran (`status` done, failed or
skipped, plus `version`, `started_at`, `seconds`, `usd` and `error`) with `total_seconds`
and `total_usd` sums, so every second and dollar is traced to its stage. Restart with
`python -m app.pipeline.runner <job_id> --resume` (or `start_job(..., resume=True)`):
finished stages with the same version and their artifact file still present are reused
(`reusable()`; recorded as `skipped` with zero cost, so no Meta call is paid twice) and
the job restarts at the stage that failed; every later stage reruns because its inputs
may have changed.

## Rules that shape the design

- Meta models only, always through `meta_client.py`; tests never reach the network.
- One stage owns one artifact and never edits another's; `manifest.json` records version,
  seconds and USD per stage.
- Video is normalized once (ingest); vision that needs pixels (keyframes, SAM) uses the
  **native original**, not the proxy.
- Every number shown to a technician has its evidence; what is not verified is said so in
  `guide.checks`.
- Rules-first safety: a model opinion enters only via `stricter()`, which can only raise.
- Job files are written atomically; one process per job, stages in order.

## Cost per job

- transcribe: `muse-voice-transcribe-1.0`, $0.18/hour, billed in whole seconds.
- identify, analyze, refine: `muse-spark-1.3`, $1.25/M input tokens ($0.15/M cached),
  $4.25/M output tokens (`PRICES` in `app/meta_client.py`).
- perception and step checks: `sam-3.1`, $0.0025/image (`PRICES` also lists $0.0002/video frame).
- Caps: `BUDGET_USD` 120 global, `JOB_BUDGET_USD` 1.0 per job (`app/config.py`); calls past
  budget raise before sending. Per-stage spend lands in `manifest.json`.
