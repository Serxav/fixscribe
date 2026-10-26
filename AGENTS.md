# FixScribe — rules for every coding agent

Read this whole file before doing anything. If anything here is unclear, STOP and ask.

## 1. What we are building
FixScribe turns a repair video recorded on a phone into a step-by-step repair guide.
It always watches the video; if the technician narrates, it also listens.
Each step has: instruction, safety warnings, the part highlighted with SAM 3.1, a numbered
screw map, a short loop clip and a "watch in video" jump. It also generates the reverse
reassembly guide and checks that every removed screw goes back (which screw goes where).

Hackathon: Meta Global AI Developer Hackathon, Indie track. Deadline: Nov 4, 2026, 9:00 PM ET.

## 2. Who does what (two agents work at the same time)

| | Muse Code | Claude Code |
|---|---|---|
| Folder | `~/fixscribe-muse` (git worktree) | `~/fixscribe` (main repo) |
| Writes code | ~65 %: everything that calls Meta (meta_client, transcribe, analyze, segment, inspector, ask), ffmpeg/OpenCV stages (ingest, scenes, frames), the web app | ~35 %: schemas.py, jobs.py, runner.py, assembly.py, eval/, tests that cover the whole pipeline |
| Reviews | — | Every Muse Code change, before it reaches main |
| Git | **Never** commits, pushes, merges, rebases or switches branches | **Only Claude Code** commits, merges and pushes, and only after Sergi says "ok" |
| Task files | Reads `tasks/<id>.md` and `tasks/<id>.review.md` | Writes them |

Sergi is the human. He passes messages between the two agents and approves every push.

## 3. How a task works (Muse Code: follow these steps exactly)
1. Sergi says: "Read tasks/<id>.md and do it."
2. Read the task file. Read every file listed in "Files to touch". Do not open other files unless needed to understand an import.
3. If something is unclear, ask ONE short question and wait.
4. Change ONLY the files listed in "Files to touch". Never touch files under "Do not touch".
5. Write or update tests for what you changed.
6. Run: `.venv/bin/pytest -q` and `.venv/bin/ruff check .` Fix until both pass.
7. STOP. Do not commit. Reply with the report in section 4.
8. If Sergi says "Read tasks/<id>.review.md", fix every point in it, run step 6 again and report again.

## 4. Report format (Muse Code, always, in Spanish)
```
HECHO: <1–3 frases>
ARCHIVOS: <lista de archivos cambiados>
TESTS: <pytest: N passed / ruff: ok>
DUDAS: <o "ninguna">
NO HECHO: <lo que falta, o "nada">
```

## 5. Hard rules (both agents)
- Everything inside the repo is in English: code, comments, commit messages, README, UI text.
- All AI inside the product uses Meta models only, always through `app/meta_client.py`.
- Never open, print, copy or commit `.env` or any key. Variable names live in `.env.example`.
- Never invent endpoints, request fields or model IDs. If it is not in https://dev.meta.ai/docs, ask.
- Every Meta API call goes through the spend counter in `app/meta_client.py`. It stops calling when `BUDGET_USD` is reached.
- Tests never call the real Meta API: mock it.
- Only code written during the hackathon (from Oct 26, 2026). Never copy code from other projects.
- Never use Streamlit. The web app is FastAPI + Jinja2 templates + Tailwind CDN + plain JavaScript.
- Do not add a dependency without asking. Allowed: fastapi, uvicorn, pydantic, openai, httpx, pillow, opencv-python-headless, jinja2, python-dotenv, python-multipart, meta_sam_parser, pytest, ruff.
- Write job files atomically: write to a temp file, then rename. One process per job, stages in order.
- Do not build anything outside section 7.

## 6. Stack and layout
Python 3.12 in `.venv`. No database: one folder per job in `data/jobs/<id>/`.

```
app/main.py            FastAPI app and routes
app/config.py          settings from environment
app/meta_client.py     the ONLY place that talks to Meta (retries, 429 backoff, spend counter)
app/schemas.py         Guide and Step models (Pydantic)
app/jobs.py            create job folder, read/write status.json
app/routes/            upload, jobs, guides, ask, export
app/pipeline/          ingest, transcribe, scenes, analyze, frames, segment, assembly, inspector, ask, runner
prompts/               analyze_v1.md, inspector_v1.md, assembly_v1.md, ask_v1.md
web/templates, web/static
tests/  eval/  demo/  docs/  tasks/
```

## 7. Scope
- Mobile-first web app: record or upload a video, progress bar, guide view, edit or regenerate one step, export Markdown.
- Narrated and silent modes. Step cuts from the spoken keyword "step" / "paso".
- Sharpest keyframe per step (±1 s), 6-second silent loop clip per step.
- SAM 3.1 part highlight; numbered screw map; reassembly with screw count check and which screw goes where.
- Inspector agent (Muse Wonder with tools segment / set_keyframe / update_step): max 5 steps, max 6 tool calls per step.
- "Ask FixScribe" by voice or text: next / back / repeat without AI; other questions answered by Spark with video seconds as proof.

## 8. Models
- `muse-spark-1.3` (never the "-contributor" ID): analysis, reassembly text, answers. `max_output_tokens` >= 4000.
- `muse-wonder-1.0`: inspector agent only.
- `sam-3.1`: one object per request, `one_bit` masks, parse with `meta_sam_parser`.
- `muse-voice-transcribe-1.0`: `POST /v1/asr/transcribe`, WAV mono 16-bit 16/24 kHz, max 10 min, `languageBias: ["Spanish","English"]`.
- Base URL: `https://api.meta.ai/v1` with the OpenAI SDK.
