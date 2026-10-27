# FixScribe — rules for every coding agent

Read this whole file before doing anything. If anything here is unclear, STOP and ask.

## 1. What we are building
FixScribe turns a repair video recorded on a phone into a step-by-step repair guide, for almost
any object: electronics, appliances, furniture, cars, plumbing, electrical, tools and more.
It first identifies what it is looking at (object, category, task, hazards), then adapts:
each category has a domain profile in `domains/<category>.json` (fasteners for SAM, parts,
tools, safety pre-checks), so a new category is one JSON file, never new code.
It always watches the video; if the technician narrates, it also listens.
Each step has: instruction, safety warnings, the part highlighted with SAM 3.1, a numbered
fastener map (screws, bolts, clips...), a short loop clip and a "watch in video" jump. It also
generates the reverse reassembly guide and checks that every removed fastener goes back.
Safety is rules first (`app/safety.py`): professional-only jobs (gas, electrical panel, airbag,
refrigerant, high-voltage battery, microwave high voltage) get no instructions. A model may only
make the safety level stricter, never lower it.

Hackathon: Meta Global AI Developer Hackathon, Indie track. Deadline: Nov 4, 2026, 9:00 PM ET.

## 2. Who does what (two agents work at the same time)

| | Muse Code | Claude Code |
|---|---|---|
| Folder | `~/fixscribe-muse` and `~/fixscribe-muse2` (two git worktrees, two tasks in parallel on different files) | `~/fixscribe` (main repo) |
| Writes code | ~65 %: everything that calls Meta (meta_client, transcribe, analyze, segment, inspector, ask), ffmpeg/OpenCV stages (ingest, scenes, frames), the web app | ~35 %: schemas.py, jobs.py, runner.py, assembly.py, eval/, tests that cover the whole pipeline |
| Reviews | — | Every Muse Code change, before it reaches main |
| Git | **Never** commits, pushes, merges, rebases or switches branches | **Only Claude Code** commits, merges and pushes, and only after Sergi says "ok" |
| Task files | Reads `tasks/<id>.md` and `tasks/<id>.review.md` | Writes them |

Sergi is the human. He approves every commit, merge and push. Claude Code launches Muse Code
headless (`muse exec`); when Claude Code is unavailable, Sergi launches Muse Code with
`tasks/HANDOFF.md`.

## 3. How a task works (Muse Code: follow these steps exactly)
0. Before every task, read `docs/HACKATHON_BRIEF.md` and `docs/ENGINEERING_STANDARD.md`.
1. You are told: "Read tasks/<id>.md and do it." (or "Read tasks/HANDOFF.md and do the queue").
2. Read the task file. Read every file listed in "Files to touch". Do not open other files unless needed to understand an import.
3. You run headless: nobody can answer. If something is unclear, make the safest choice that stays inside the task and write it under DUDAS.
4. Change ONLY the files listed in "Files to touch". Never touch files under "Do not touch".
5. Write or update tests for what you changed.
6. Run: `.venv/bin/pytest -q`, `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` Fix until all pass.
7. Answer the five questions at the end of `docs/HACKATHON_BRIEF.md`.
8. STOP. Do not commit. Reply with the report in section 4. In HANDOFF mode, also write it to `tasks/<id>.report.md`.
9. If you are told "Read tasks/<id>.review.md", fix every point in it, run step 6 again and report again.

## 4. Report format (Muse Code, always, in Spanish)
```
HECHO: <1–3 frases>
ARCHIVOS: <lista de archivos cambiados>
TESTS: <pytest: N passed / ruff: ok>
JURADO: <qué criterio de la rúbrica mejora esta tarea y por qué>
DUDAS: <o "ninguna">
NO HECHO: <lo que falta, o "nada">
```
If you cannot fill JURADO, you have not understood the task: re-read the task and the brief.

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
- Identify stage first; domain profiles per category; rules-first safety gate.
- Narrated and silent modes. Step cuts from the spoken keyword "step" / "paso".
- Sharpest keyframe per step (±1 s), 6-second silent loop clip per step.
- SAM 3.1 part highlight; numbered fastener map; reassembly with fastener count check and which fastener goes where.
- Inspector agent (Muse Wonder with tools segment / set_keyframe / update_step): max 5 steps, max 6 tool calls per step.
- "Ask FixScribe" by voice or text: next / back / repeat without AI; other questions answered by Spark with video seconds as proof.

## 8. Models
- `muse-spark-1.3` (never the "-contributor" ID): analysis, reassembly text, answers. `max_output_tokens` >= 4000.
- `muse-wonder-1.0`: inspector agent only.
- `sam-3.1`: one object per request, `one_bit` masks, parse with `meta_sam_parser`.
- `muse-voice-transcribe-1.0`: `POST /v1/asr/transcribe`, WAV mono 16-bit 16/24 kHz, max 10 min, `languageBias: ["Spanish","English"]`.
- Base URL: `https://api.meta.ai/v1` with the OpenAI SDK.
