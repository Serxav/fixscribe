# FixScribe architecture (backend v2)

A phone video of a repair goes in; a verified step-by-step guide comes out. The backend is a
pipeline of small stages. **Each stage reads typed artifacts and writes exactly one artifact** in
the job folder; nothing is shared in memory and nothing is overwritten by another stage.

## Pieces
| Piece | Code | Job |
|---|---|---|
| Web app | `app/main.py`, `app/routes/` | upload, progress API, guide page, media files |
| Job store | `app/jobs.py` | one folder per job `data/jobs/<id>/`, `status.json` (locked, atomic), stale-job detection |
| Runner | `app/pipeline/runner.py` | one process per job, stages in order, `manifest.json` (version, seconds, dollars per stage) |
| Artifacts | `app/schemas.py`, `app/artifacts.py` | one Pydantic model per file, one atomic load/save |
| Meta door | `app/meta_client.py` | the only code that talks to Meta: Spark, Voice, SAM, Files; retries, global and per-job budget, spend log |
| Evaluation | `eval/score.py`, `eval/run_eval.py` | labelled videos → step F1, boundaries, screws, seconds, dollars |

## Stages (in order)
| # | Stage | Reads | Writes | Uses | If it fails |
|---|---|---|---|---|---|
| 1 | ingest | `original.*` | `ingest.json`, `video.mp4` (CFR 30 fps, ≤720 p, SDR BT.709), `audio.wav` | ffmpeg | job fails (clear message) |
| 2 | transcribe | `audio.wav` | `transcript.json` (turns with times) | Muse Voice | warning, video treated as silent |
| 3 | signals | `video.mp4` | `signals.json` (motion with shake compensation, scene changes, candidates) | OpenCV | warning |
| 4 | scenes | transcript, ingest | `scenes.json` (voice cuts as intervals) | — | job fails |
| 5 | analyze | `video.mp4`, transcript, scenes | `analysis.json` (+ `analysis_raw.txt`) | Muse Spark, strict JSON schema | job fails |
| 6 | fusion | analysis, scenes, signals | `fusion.json` (snapped boundaries, source, agreement, confidence) | — | warning |
| 7 | refine | analysis, fusion, transcript, proxy | `refine.json` (uncertain steps re-read on timecoded clips) | Muse Spark | warning |
| 8 | plan | analysis, fusion, refine, ingest, transcript | `plan.json` (final steps and times; every change logged) | — | job fails |
| 9 | frames | plan, signals, proxy, original | `frames.json`, `stills/NN.png` (native), `steps/NN.jpg`, `steps/NN.mp4` | OpenCV, ffmpeg | warning |
| 10 | perception | plan, frames, original | `perception.json` (part box, screw ledger), `steps/NN_overlay.jpg` | SAM 3.1 | warning |
| 11 | publish | plan, frames, perception | `guide.json` (+ reassembly, checks) | — | job fails |

The runner deletes a stage's previous output before it runs, so a failed optional stage can never
leave stale data behind, and it records every stage in `manifest.json`.

## Rules that shape the design
- Meta models only, always through `meta_client.py`; tests never reach the network (`tests/conftest.py`).
- Every number shown to a technician has its evidence: times from voice/vision/Spark with their
  source, screws from Spark's count **and** SAM's before/after ledger; what is not verified is said
  so in `guide.checks`.
- Video is normalized once (ingest); vision that needs pixels (keyframes, SAM) uses the **native
  original**, not the proxy.
