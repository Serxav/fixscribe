# Publishing FixScribe for the judges

The camera and microphone only work over https, so judges need a hosted address.

1. Connect this GitHub repository to a host that builds the `Dockerfile` and gives https.
2. Use at least 2 GB of memory and a persistent volume mounted at `/srv/data`.
3. Set these variables in the host's panel, never in the repository:

| Variable | Value | Why |
|---|---|---|
| `MODEL_API_KEY` | your key | Meta calls |
| `BUDGET_USD` | `25` | total this server may spend |
| `DAILY_JOB_LIMIT` | `3` | at most 3 new videos a day |
| `LIVE_BUDGET_USD` | `10` | the coach on the sample guide |
| `LIVE_MAX_CALLS` | `2000` | coach calls on the sample guide |
| `ENABLE_INSPECTOR` | `false` | the agent costs more per job |
| `DEMO_JOB` | the folder in `demo/` | the sample guide on the landing |

The spend counter on the server starts at zero, separate from local runs. Check Usage on
dev.meta.ai every day, and turn the service off after judging.

To change the sample: `python -m scripts.pack_demo data/jobs/<id>`, commit `demo/<id>`. Only pack a
video you have the right to publish.
