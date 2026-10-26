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

Two coding agents worked side by side. Muse Code wrote most of the code that calls Meta models,
the video stages and the web app. Claude Code wrote the core models, the job store and the
pipeline tests, and reviewed every change before it reached `main`.

## License

MIT. See [LICENSE](LICENSE).
