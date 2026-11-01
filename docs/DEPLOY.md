# Publishing FixScribe for the judges

The camera and microphone only work over https, so judges need a hosted address.

1. Connect this GitHub repository to a host that builds the `Dockerfile` and gives https.
2. Use at least 4 GB of memory (a 720p video peaked at 1.1 GB on 6 steps; 1080p needs more) and a persistent volume mounted at `/srv/data`.
3. Set these variables in the host's panel, never in the repository:

| Variable | Value | Why |
|---|---|---|
| `MODEL_API_KEY` | your key | Meta calls |
| `BUDGET_USD` | `35` | total this server may spend |
| `JOB_BUDGET_USD` | `2.5` | one 8.5-minute video cost $1.47; a lower cap cuts the guide short |
| `DAILY_JOB_LIMIT` | `3` | at most 3 new videos a day |
| `LIVE_BUDGET_USD` | `10` | the coach on the sample guide |
| `LIVE_MAX_CALLS` | `2000` | coach calls on the sample guide |
| `ENABLE_INSPECTOR` | `false` | the agent costs more per job |
| `DEMO_JOB` | the folder in `demo/` | the sample guide on the landing |

Before the first judge: open the address on a phone, try the camera and the microphone over https,
and run one short video through.

The spend counter on the server starts at zero, separate from local runs. Check Usage on
dev.meta.ai every day, and turn the service off after judging.

To change the sample: `python -m scripts.pack_demo data/jobs/<id>`, commit `demo/<id>`. Only pack a
video you have the right to publish.
