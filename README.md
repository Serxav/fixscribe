# FixScribe

Record a repair on your phone. Get a step-by-step repair guide.

FixScribe always watches the video and, if you narrate, it also listens. Each step gets an
instruction, safety warnings, the part highlighted with SAM 3.1, a numbered screw map, a short
loop clip and a "watch in video" jump. It also writes the reverse reassembly guide and checks
that every removed screw goes back where it came from.

Made for the Meta Global AI Developer Hackathon (Indie track).

## What a technician gets

1. **Film the repair** on a phone, narrated or silent, any category: electronics, appliances,
   furniture, bikes, cars, plumbing and more. Saying "step" / "paso" cuts the steps.
2. **A guide in a few minutes**: each step has an instruction, safety warnings, the part
   highlighted, a numbered fastener map, a 6-second loop clip and a "watch in video" jump.
3. **Putting it back**: the reverse guide, plus a check that every fastener taken out goes back.
4. **Proof on every claim**: each step boundary, instruction, fastener count and part is graded
   verified / supported / unverified, with the video seconds and words behind it.
5. **Safety first**: fixed rules (`app/safety.py`) refuse professional-only jobs (gas, electrical
   panel, airbag, refrigerant, high-voltage battery, microwave). A model can only make it
   stricter.
6. **Fix it by hand**: tap a fastener the guide missed and SAM 3.1 follows it through the step;
   tap a wrong number to remove it.
7. **While repairing**: "Ask FixScribe" by voice or text (answers point to the video second),
   a live camera mode that says which step you are on, a photo check ("is this step done?")
   and a printable fastener tray.

## How it uses Meta models

| Model | What it does in FixScribe |
|---|---|
| `muse-spark-1.3` | identifies the object, category and hazards; reads the whole video and transcript to write the steps; re-reads unclear steps on timecoded clips; checks every fastener candidate on three zoomed views; answers questions |
| `muse-voice-transcribe-1.0` | timestamped words; the spoken "step" / "paso" become the step cuts |
| `sam-3.1` (images) | highlights the part; finds fastener candidates on the full frame and on zoomed tiles |
| `sam-3.1` (video) | follows each fastener through the step, so a fastener counts only if it appears or disappears where the step says; follows a point the user taps |
| `muse-wonder-1.0` | the agent: it looks at frames, points at parts, adds steps and asks the person when unsure, then files the guide for sign-off |
| MMS-TTS (Meta open weights, CC-BY-NC 4.0, run locally) | reads the film and the live coach aloud in English; install it with `python -m scripts.get_voice`, otherwise the device voice is used |

Unexpected uses:

- **SAM 3.1 as a fastener counter and verifier.** Candidates come from SAM on the frame and on
  zoomed tiles, SAM video follows them over time, and Spark confirms each one by number
  (set-of-mark), never by guessing coordinates.
- **Voice turns as step cuts.** The narration itself is the editing tool.
- **An agent with eyes.** Muse Wonder uses SAM and frames as tools and stops to ask a person.

Every call goes through `app/meta_client.py`: retries, 429 backoff, a global and a per-job
budget, and a spend log per stage.

## Evaluation (`eval/`)

Hand-labelled answer keys, no Meta calls when scoring:

| Exam | Command | Result |
|---|---|---|
| Part and fastener finding on 20 photos | `python -m eval.detect_score` | recall 0.89, precision 1.00, 16 of 20 perfect |
| Fasteners in a real 16-step furniture video (720p) | `python -m eval.video_score` | recall 0.75, precision 1.00: no invented fastener; steps with no visible fastener left empty |
| Whole pipeline on labelled videos | `python -m eval.run_eval --reuse` | step F1, boundaries within ±2 s, fastener counts, seconds and dollars per stage |

Honest limits: fasteners hidden inside the wood or under a hand cannot be seen; then the count
comes from the analysis and the guide says so. Small fasteners need a 1080p or 4K video, and the
guide warns when the video is smaller.

## Run locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then add your key
.venv/bin/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 on a computer or phone and upload a video.

Tests and lint (about 700 tests, Meta always mocked):

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Docker:

```bash
docker build -t fixscribe .
docker run --env-file .env -p 8000:8000 fixscribe
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how it works.

## Built during the hackathon (Oct 26 – Nov 4, 2026)

All code in this repository was written during the hackathon, starting on Oct 26, 2026.

## Built with Muse Code

Muse Code (Meta's coding agent, running `muse-spark-1.3`) wrote much of the code that calls Meta
models, the video stages and the web app, from small written tasks. Every task, review and report
is kept in [`tasks/`](tasks/):

1. A task file `tasks/<id>.md` names the files to touch, the function signatures, the exact Meta
   docs pages and fields, testable "done when" checks, and why the task matters for judging.
2. Muse Code runs headless (`muse exec`) in its own git worktree, sandboxed: it can edit files
   and run tests, but it cannot commit, push or reach the network from the shell.
3. Muse Code reports in a fixed format; each change is reviewed against a checklist, and
   problems go to `tasks/<id>.review.md` for Muse Code to fix.
4. Only reviewed work is committed and merged. Each Muse Code commit says
   "Written by Muse Code (task <id>)".

## License

MIT. See [LICENSE](LICENSE).
