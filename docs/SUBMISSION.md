# Submission text

Fill the items in brackets before sending. Every number here comes from the README's evaluation.

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
and a proof grade. It also writes the way back and counts the screws. While you work, a live coach
follows your camera, marks the parts and takes voice commands.

**How it uses Meta models:**

- `muse-spark-1.3` identifies the job, writes the steps, points at parts, reviews each step frame by
  frame and follows the live camera.
- `sam-3.1` cuts out what Spark points at and follows fasteners through the clip.
- `muse-voice-transcribe-1.0` times the narration, cuts the steps and hears the user in the coach.
- `muse-wonder-1.0` is an optional agent that investigates a guide with SAM and frames as tools.
- MMS-TTS, Meta's open weights, runs locally for the voice.

**Technical depth:** Stages that resume after a failure, atomic job files, retries and 429 backoff,
a per-job and global spend counter, about 800 tests with Meta mocked, and exams against answer keys.

**Results (2026-11-01, two videos):** the coach is on the right step 88 % and 95 % of the time within
8 s, and 76 % and 80 % at the exact moment. Marks are right 93 % and 74 % of the time. On one
8.5-minute repair, 8 of 10 shown parts were surely right by eye, and no screw was confirmed in its
720p footage. [Add the numbers from the demo video.]

**Limits:** The coach answers in about 8 s and marks take about 25 s. Small screws need 1080p or
better. Tried on few videos so far. [State whether real technicians have tried it. If none have, say
so.]

**Built with:** All code written from Oct 26, 2026. Muse Code wrote the first version of several
stages, with its tasks in `tasks/`; the rest was written with another coding agent, as each commit
states.

**Links:** [Deployed address] · [GitHub repository] · [3-minute video]
