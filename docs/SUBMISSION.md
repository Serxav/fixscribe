# Submission text

Every number here comes from the README's evaluation.

**Name:** FixScribe

**Track and theme:** Indie · Build for Your World

**One line:** Record a repair on your phone and get a step-by-step guide that shows the part, the
screws and the second of video behind each step.

**Problem — "Which step am I on, and what is this part?":** Repair videos and manuals assume you
can watch and work at the same time. With both hands inside a device you cannot scroll back to find
which step you are on, what the part in front of you is called or what comes next. And the person who
already did the repair, whose video shows all of it, has no quick way to turn it into a guide someone
else can follow.

**What it does:** Upload one video of a repair or assembly, narrated or silent. FixScribe identifies
the object and the hazards, refuses professional-only jobs with fixed rules, and writes the steps.
Each step has the part cut out on the frame, numbered screws when the video shows them, a short clip
and a proof grade. The way back follows each part through the video, so only what is still off at
the end goes back, with a screw tally you tick as you go. While you work, a live coach follows your
camera, marks the parts and takes voice commands or typed questions; each answer names its step and
plays that moment of the video.

**How it uses Meta models:**

- `muse-spark-1.3` identifies the job, writes the steps, points at parts, reviews each step frame by
  frame and follows the live camera.
- `sam-3.1` cuts out what Spark points at and follows fasteners through the clip.
- `muse-voice-transcribe-1.0` times the narration, cuts the steps and hears the user in the coach.
- `muse-wonder-1.0` is an optional agent that investigates a guide with SAM and frames as tools.
  On one real 8.5-minute video it filed 15 steps and 5 SAM-proven parts in 13 turns for $0.69.

**Technical depth:** Stages that resume after a failure, atomic job files, retries and 429 backoff,
a per-job and global spend counter, 965 tests with Meta mocked (strange model answers and odd videos
included: a job ends with a guide or a clear sentence, never a crash), and exams against answer keys.

**Results (2026-11-01, two videos):** the coach is on the right step 88 % and 95 % of the time within
8 s, and 76 % and 80 % at the exact moment. Marks are right 93 % and 74 % of the time. On one
8.5-minute repair, 8 of 10 shown parts were surely right by eye, and no screw was confirmed in its
720p footage. Typed questions to the coach on that guide (2026-11-02): 3 of 3 right, two pointing to
the right step and second, one off-topic question refused. A rerun of the phone exam on 2026-11-02:
marks right 89 %, the step's own part 10 of 11, median 20 s.
Four sample guides made from openly licensed internet videos (a laptop, a game console, a harp, a
seat cushion) are in `demo/`, 7 to 15 steps each.

**Limits:** On a computer of its own the coach reads a camera frame in about 8 s, marks take about
20 s and a typed question 2 to 4 s; on the shared live app it is 10 to 20 s, up to a minute and 5 to
10 s. Small screws need 1080p or
better. Tried on few videos so far, and no repair technician has tried it yet.

**Built with:** All code written from Oct 26, 2026. Muse Code wrote the first version of several
stages, with its tasks in `tasks/`; the rest was written with other AI coding assistants, as each commit
states.

**Links:** Live app: https://fixscribe-wpf3.onrender.com · Repository: https://github.com/Serxav/fixscribe · Sample guides, no install:
https://github.com/Serxav/fixscribe/tree/main/demo · Demo film: https://www.youtube.com/watch?v=bpZMs6h1uUo

**How to try it** (step by step in `docs/TRY_IT.md`):
A. The live app, nothing to install: open a finished guide (laptop, game console, harp, seat cushion),
then its live coach with the guide's own video, or your own camera and voice.
B. Your own video, on your computer: a few commands with or without Docker, and a Meta key, then upload a video
up to 10 minutes; it becomes a guide in about 20 minutes. The free live server is too small to
process new videos.
C. Without running anything: the 3-minute film and `demo/`, with every photo, cut-out and clip of the
four guides and recorded clips of the live coach.

**Waiting times on the live app (slow, not stuck):** the app normally opens at once (about 1 minute if the free server fell asleep), then 10 to 20 s per coach answer, up to about 1 minute for part marks, 5 to 10 s per question. A new guide from a 45 s video takes about 20
minutes on your computer. The server is shared: several coaches at once take turns, so they can be a little slower; one coach per judge at a time works best.
