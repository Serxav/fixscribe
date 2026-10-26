# FixScribe

Record a repair on your phone. Get a step-by-step repair guide.

FixScribe always watches the video and, if you narrate, it also listens. Each step gets an
instruction, safety warnings, the part highlighted with SAM 3.1, a numbered screw map, a short
loop clip and a "watch in video" jump. It also writes the reverse reassembly guide and checks
that every removed screw goes back where it came from.

Made for the Meta Global AI Developer Hackathon (Indie track).

## Run locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then add your key
.venv/bin/uvicorn app.main:app --reload
```

Tests and lint:

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

## Built with Muse Code and Claude Code

Two coding agents worked side by side. Muse Code (Meta's coding agent, running
`muse-spark-1.3`) wrote most of the code that calls Meta models, the video stages and the web app.
Claude Code wrote the core models, the job store, the runner, the evaluation and the pipeline
tests, and reviewed every change before it reached `main`.

How it worked, all visible in [`tasks/`](tasks/):

1. Claude Code writes a small, concrete task: `tasks/<id>.md` (files to touch, function
   signatures, exact Meta docs pages and fields, testable "done when" checks, and why the task
   matters for judging).
2. Muse Code runs headless (`muse exec`) in its own git worktree, sandboxed: it can edit files
   and run tests, but it cannot commit, push or reach the network from the shell.
3. Muse Code reports in a fixed format. Claude Code reviews it with a checklist; problems go to
   `tasks/<id>.review.md` and Muse Code fixes them.
4. Only reviewed work is committed and merged. Each Muse Code commit says
   "Written by Muse Code (task <id>)".

Every task file, review and report is kept in the repository as a record of the process.

## License

MIT. See [LICENSE](LICENSE).
