# Submission text

Every number here comes from the README's evaluation.

**Name:** FixScribe

**Track and theme:** Indie · Build for Your World

**One line:** Record a repair on your phone and get a step-by-step guide that shows the part, the
screws and the second of video behind each step.

**Problem:** Most instructions are written by someone who already knows how, so they skip the step
where you get stuck. The person who just did the job knows it best, but turning a video into a guide
takes hours.

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
- MMS-TTS, Meta's open weights, runs locally for the voice.

**Technical depth:** Stages that resume after a failure, atomic job files, retries and 429 backoff,
a per-job and global spend counter, 959 tests with Meta mocked (strange model answers and odd videos
included: a job ends with a guide or a clear sentence, never a crash), and exams against answer keys.

**Results (2026-11-01, two videos):** the coach is on the right step 88 % and 95 % of the time within
8 s, and 76 % and 80 % at the exact moment. Marks are right 93 % and 74 % of the time. On one
8.5-minute repair, 8 of 10 shown parts were surely right by eye, and no screw was confirmed in its
720p footage. Typed questions to the coach on that guide (2026-11-02): 3 of 3 right, two pointing to
the right step and second, one off-topic question refused. A rerun of the phone exam on 2026-11-02:
marks right 89 %, the step's own part 10 of 11, median 20 s.
Four sample guides made from openly licensed internet videos (a laptop, a game console, a harp, a
seat cushion) are in `demo/`, 7 to 15 steps each.

**Limits:** The coach reads a camera frame in about 8 s and marks take about 20 s; a typed question
is answered in 2 to 4 s. Small screws need 1080p or
better. Tried on few videos so far, and no repair technician has tried it yet.

**Built with:** All code written from Oct 26, 2026. Muse Code wrote the first version of several
stages, with its tasks in `tasks/`; the rest was written with other AI coding assistants, as each commit
states.

**Links:** Live app: https://fixscribe-wpf3.onrender.com · Repository: https://github.com/Serxav/fixscribe · Sample guides, no install:
https://github.com/Serxav/fixscribe/tree/main/demo · Demo film: (link added when uploaded)

**How to try it** (step by step in `docs/TRY_IT.md`): open the live app on a phone or computer: the Dell sample guide and its live coach
are on the landing, and any repair video of up to 2 minutes can be uploaded. Or run it locally (the
README's "Run it" section). With no key, `DEMO_JOB=137c1ed0730d` opens a
sample guide in the app. With a Meta key, upload any repair video.
