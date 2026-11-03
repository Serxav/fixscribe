# Publishing FixScribe for the judges

The camera and microphone only work over https, so judges need a hosted address.

1. Connect this GitHub repository to a host that builds the `Dockerfile` and gives https.
2. Use at least 4 GB of memory (a 720p video peaked at 1.1 GB on 6 steps; 1080p needs more) and a persistent volume mounted at `/srv/data`.
3. Set these variables in the host's panel, never in the repository:

| Variable | Value | Why |
|---|---|---|
| `MODEL_API_KEY` | your key | Meta calls |
| `BUDGET_USD` | what is left of the credit, minus a margin (for example `80`) | the one hard ceiling: past it no call is sent |
| `JOB_BUDGET_USD` | `2.5` | one 8.5-minute video cost $1.47; a lower cap cuts the guide short |
| `DAILY_JOB_LIMIT` | `50` | judges may film as many repairs as they like |
| `MAX_RUNNING_JOBS` | `2` | videos processed at once; more wait in line, so 4 GB is never run out |
| `LIVE_BUDGET_USD` | `30` | the coach on the sample guide, shared by every judge; a judge's own guide stops at $5 |
| `LIVE_MAX_CALLS` | `10000` | coach calls on the sample guide; a judge's own guide stops at 1000 (about an hour) |
| `ENABLE_INSPECTOR` | `true` | judges can try the Muse Wonder agent (about $0.70 a run) |
| `DEMO_JOB` | the folder in `demo/` | the sample guide on the landing |
| `TRUST_PROXY` | `true` | the host's proxy adds the visitor's address; without it every visitor counts as one |
| `VISITOR_VIDEOS_PER_DAY` | `0` | 0 = no per-visitor limit, so judges can try everything; a number turns it on |
| `VISITOR_COACH_MINUTES_PER_DAY` | `0` | same, for minutes of live coach a day |
| `VISITOR_QUESTIONS_PER_HOUR` | `0` | same, for voice and typed questions an hour |
| `VISITOR_ACTIONS_PER_HOUR` | `0` | same, for step checks, fastener taps and agent runs an hour |

For judging the per-visitor limits stay off and only `BUDGET_USD` stops spending. If someone abuses
the server, set a number on any of them in the panel: visitors are counted by address, in memory,
and one over a limit gets a 429 with one sentence; the coach stops sending frames when it gets one.
More than 40 coach frames a minute from one address is always refused: only a script sends that.

Before the first judge: open the address on a phone, try the camera and the microphone over https,
and run one short video through. Then, inside the running image, check that ffmpeg refuses a playlist
named as a video (expect an error, and no secret in the output):

```bash
printf '#EXTM3U\n#EXTINF:1,\n/proc/self/environ\n#EXT-X-ENDLIST\n' > /tmp/fake.mp4
ffprobe -v error -format_whitelist mov,mp4,m4a,3gp,3g2,mj2 -protocol_whitelist file \
  -show_format /tmp/fake.mp4
```

The spend counter on the server starts at zero, separate from local runs. Check Usage on
dev.meta.ai every day. Judging runs until Nov 8: keep the service on until then, and turn it off
after.

To change the sample: `python -m scripts.pack_demo data/jobs/<id>`, commit `demo/<id>`. Only pack a
video you have the right to publish.

## Last day: from a new video to the submission

The deadline is Nov 4, 2026, 9:00 PM ET (03:00 on Nov 5 in Spain). Leave at least three hours for
these steps; the guide alone takes about 30 minutes on an 8.5-minute video.

1. **Film.** A repair you have the right to publish, 2 s to 10 min, good light, the part filling
   the frame, 1080p if screws matter. Say "step" (or "paso") before each step.
2. **Guide.** Put it in `samples/` and run `.venv/bin/python scripts/run_video.py samples/<name>.mp4`.
   It costs about $1.50 for 8.5 minutes and prints the job id. Start the server with
   `.venv/bin/uvicorn app.main:app`, open `http://localhost:8000/guides/<id>` and read every step; regenerate a wrong one from the page.
3. **Sample.** `python -m scripts.pack_demo data/jobs/<id>`. It leaves out the original upload,
   visitors' photos, the agent's folder and backups, and shrinks a video GitHub would refuse.
   Commit `demo/<id>`.
4. **Host.** Push, then set `DEMO_JOB=<id>` and the other variables in the table above in the
   host's panel. Open the address on a phone: the landing, the sample guide, the coach with the
   camera and the microphone, one typed question.
5. **Submit.** Fill the brackets in `docs/SUBMISSION.md`, add the deployed address, the repository
   and the film, and send the form before the deadline.
