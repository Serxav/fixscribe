# FixScribe architecture

FixScribe turns a phone repair video into a step-by-step repair guide. It always watches the
video; if the technician narrates, it also listens.

## Four pieces

1. **Web app** (`app/main.py`, `app/routes/`, `web/`): FastAPI + Jinja2 + Tailwind CDN + plain
   JavaScript. Mobile-first: record or upload, progress bar, guide view, edit or regenerate a step,
   export Markdown, "Ask FixScribe".
2. **Job store** (`app/jobs.py`): no database. One folder per job in `data/jobs/<id>/` with the
   input video, intermediate files and `status.json`. Every file is written atomically (temp file,
   then rename).
3. **Pipeline** (`app/pipeline/`, driven by `runner.py`): one process per job, stages in order.
   A failing stage marks the job as failed with a clear message; it never crashes the server.
4. **Meta client** (`app/meta_client.py`): the only door to Meta. Every call to Muse Spark,
   Muse Wonder, SAM 3.1 or Muse Voice goes through it. It retries with growing waits on 429 and
   timeouts and counts spend in `data/spend.json`. It refuses new calls once `BUDGET_USD` is
   reached.

```
phone ──► web app ──► job store ◄──► pipeline runner ──► meta_client ──► Meta API
                         ▲                                   │
                         └──────── data/spend.json ◄─────────┘
```

## Thirteen phases

| # | Phase | Module | Uses Meta |
|---|-------|--------|-----------|
| 1 | Upload and validate (mp4, length <= `MAX_VIDEO_SECONDS`) | `routes/upload.py`, `jobs.py` | no |
| 2 | Ingest: probe the video, extract WAV mono 16-bit 16 kHz | `pipeline/ingest.py` | no |
| 3 | Transcribe if there is speech (narrated mode) | `pipeline/transcribe.py` | Muse Voice |
| 4 | Step cuts from the keyword "step" / "paso" and scene changes | `pipeline/scenes.py` | no |
| 5 | Analyze video (+ transcript) into draft steps with seconds | `pipeline/analyze.py` | Muse Spark |
| 6 | Sharpest keyframe per step (±1 s) | `pipeline/frames.py` | no |
| 7 | 6-second silent loop clip per step | `pipeline/frames.py` | no |
| 8 | Part highlight on the keyframe | `pipeline/segment.py` | SAM 3.1 |
| 9 | Numbered screw map | `pipeline/segment.py` | SAM 3.1 |
| 10 | Inspector: check and fix weak steps (max 5 steps, 6 tool calls each) | `pipeline/inspector.py` | Muse Wonder |
| 11 | Reassembly guide and screw count check | `pipeline/assembly.py` | Muse Spark |
| 12 | Validate and save `guide.json` (`app/schemas.py`) | `pipeline/runner.py` | no |
| 13 | Serve: guide view, edit, export Markdown, Ask FixScribe | `routes/`, `pipeline/ask.py` | Muse Spark |

## Rules that shape the design

- Meta models only, always through `meta_client.py`. Tests mock it.
- Job files are written atomically. One process per job.
- Seconds are validated by the schemas: `start_s < end_s`, keyframe inside the step, steps inside
  the video.
