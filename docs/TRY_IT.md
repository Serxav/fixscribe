# Try FixScribe, step by step

There are three ways to try it. Each one is explained step by step below.

| Way | What you need | What you get | Set-up |
|---|---|---|---|
| [**A. The live app**](#a-the-live-app) | a phone or computer | the four finished guides, the live coach with camera and voice, your own video up to 2 minutes | none |
| [**B. On your own computer**](#b-on-your-own-computer) | Docker, or Python 3.12 and ffmpeg; a Meta Model API key | everything, with videos up to 10 minutes, no waiting for other people's videos, and Meta's MMS-TTS voice | about 5 to 10 minutes |
| [**C. Without running anything**](#c-without-running-anything) | a browser | the 3-minute film, and every photo, cut-out, clip and proof of the four guides, plus recorded clips of the live coach | none |

---

## A. The live app

**Address: https://fixscribe-wpf3.onrender.com**

It works on a phone (Safari on iPhone, Chrome on Android) or a computer. Nothing to install, no
account. The first button on the landing is **Upload a video**: start your own video first
([A4](#a4-your-own-repair-video)), since it takes about 20 minutes, and try A1 to A3 meanwhile in another tab. It runs on a server with 2 GB of memory that is always on, so it opens at once.

**Meta credit for your tests: about €55 is left (2026-11-04).** It is shared by all the judges and
pays for every AI call on the live app: guides from your videos, the live coach and questions. To
protect it, the live app stops every Meta call once it has spent **$50 in all**; after that it
answers that it reached its spend limit. A 45-second video costs about $0.80 and an hour of the
coach a few dollars, so there is room for plenty of tests. If it does stop, way B (your own computer,
your own key) and way C still work.

**You can upload your own video.** MP4 or MOV, **up to 2 minutes** (30 to 60 seconds is the quickest
to try), narrated or silent. It becomes a guide in **about 20 minutes** for a 45-second video, and
**one video is processed at a time**: if another one is running, yours waits for it and then starts
by itself. Steps in [A4](#a4-your-own-repair-video).

### How long things take (it is slow, not stuck)

Measured on the live app on 2026-11-04. Every wait ends by itself: nothing needs a reload.

| What | How long | What you see meanwhile |
|---|---|---|
| Opening the app | **at once** | |
| Opening a guide, its photos and clips | under 1 s | |
| The coach's first answer, and each new one | **10 to 20 s** | **Looking…**; with the guide's video, the video pauses until the answer comes |
| The part marks on a new step | **up to about 1 minute** | the step and its instruction are already shown; the marks appear dashed, then solid (or go away if Spark does not confirm them) |
| A typed or spoken question | **5 to 10 s** | **Thinking…**, then the answer and a button to that moment of the video |
| The coach following a whole guide with its video | **about 15 to 20 minutes** for 11 steps | the step changes on its own; a 30× speed-up is in [demo/](../demo/README.md#the-live-coach-on-the-dell-guide) |
| Several people using the coach at the same moment | **a little longer** | the server is shared, so coaches take turns: part marks are worked out one at a time, answers three at a time. A step whose marks waited too long shows none; the next step gets them |
| Turning your video into a guide | **about 20 minutes** for a 45 s video | a progress page with every stage as it runs |
| Two people uploading at the same moment | the second waits for the first, then about 20 more minutes | **Waiting for another video to finish…**, then the stages |

**One coach per judge at a time works best.** The live app runs on one server shared by everyone
who opens it. When several coaches run at once they wait for each other instead of overloading it.
Close the coach tab when you are done, so the next person does not wait for it.

### A1. A finished guide (1 minute)

1. Open the address. Under the upload buttons, the landing lists **four finished guides** (a laptop, a
   game console, a harp, a seat cushion); each opens in the app with its own live coach. Tap
   **See a finished guide** for the first one. It is the guide FixScribe wrote from a
   Dell Latitude 7455 disassembly video ([source and licence](../demo/README.md)).
2. Scroll the **Steps**. Each one has a photo where the part is outlined (SAM 3.1's cut-out of what
   Muse Spark pointed at) and the screws are circled and numbered in the order they come out.
3. Tap **Clip** to see the 6-second loop of that step, or **Watch in video** to jump to that second
   of the original video.
4. Look at the **Parts** catalog and the **proof** of each step: what could not be proven is marked.
5. Switch to the way back (**Put back**): the steps in reverse, with a tally of every screw that has
   to return. **Print fastener tray** gives a sheet to sort the screws on.

The sample guides are read-only: buttons that would change them answer "The sample guide cannot be
changed."

### A2. The live coach with nothing to repair (3 minutes)

The coach is made for the guide of your own video (A4, step 4). To see it before yours is ready:

1. Open a finished guide and tap **Live coach** (or **live coach** next to it in the landing's list).
2. Tap **Nothing to repair right now? Use this guide's video**. The guide's own video plays where
   your camera would be.
3. Watch the panel: the coach says which step it sees (**Step 1 of 11**), its state (**On track**,
   **Step done**, **Check this**), and what comes next. The video **waits for the coach** at every
   frame: each answer takes 10 to 20 s.
4. When a new step starts, the parts get marked on the picture: dashed while SAM 3.1 cuts them out,
   solid once Spark has checked them. The marks take up to about a minute, and a mark Spark does
   not confirm is taken away rather than shown.
5. Type a question in **Ask about this repair…**, for example `How many screws hold the battery?`.
   The answer names its step and has a button that plays that moment of the video.
6. Buttons at the bottom: ⏸ hold the video, ‹ › previous / next step, ↻ repeat, 🔊 voice on or off,
   🎙️ talk to it.

A clip of this, recorded on 2026-11-04, is in [demo/](../demo/README.md#the-live-coach-on-the-dell-guide).

### A3. The live coach with your camera and voice

1. On the coach page of a guide tap **Start the camera** and allow the camera.
2. Point it at the object of that guide: your own object on your own guide (A4), or a laptop's
   underside on the Dell guide. It shows **Check this** or **Looking…** when the view does not
   match a step.
3. Tap 🎙️ and allow the microphone. Say **"next"**, **"back"** or **"repeat"** (no AI needed), or ask
   a question out loud.

### A4. Your own repair video

1. Film or pick a repair or assembly video: MP4 or MOV, **up to 2 minutes** (30 to 60 seconds is
   the quickest). Good light, the part filling the frame, 1080p if screws matter. Narrated or
   silent; saying "step" (or "paso") before each step cuts the steps exactly there.
2. On the landing tap **Record a video** (phone camera) or **Upload a video** (a file).
3. The progress page shows every stage as it runs: what it heard, the steps on the timeline, the
   step cards. **Leave it open**: a 45-second video takes about 20 minutes. If another video is
   running it shows **Waiting for another video to finish…** first.
4. Then **Open the guide**: the same kind of guide as in A1, from your video. Its **Live coach**
   button coaches that guide. **Agent console** shows Muse Wonder checking the guide with
   SAM as a tool.

Longer videos, up to 10 minutes, work on your own computer (B).

---

## B. On your own computer

Everything runs on your machine; only the AI calls go to Meta's servers, paid by your own Meta key.
Videos can be up to 10 minutes, nobody else's video is ahead of yours, and the steps are read aloud
with Meta's MMS-TTS voice.

### B1. What you need

- A **Meta Model API key** (from dev.meta.ai).
- **Either Docker** (the easiest: ffmpeg and the voice are inside the image), **or Python 3.12** and
  **ffmpeg** (`brew install ffmpeg` on a Mac, `sudo apt install ffmpeg` on Ubuntu/Debian).
- About 2 GB of free memory while a video is being turned into a guide.

### B2. Get the code and add your key

```bash
git clone https://github.com/Serxav/fixscribe.git
cd fixscribe
cp .env.example .env
```

Open `.env` in a text editor and put your key after `MODEL_API_KEY=` (no quotes, no spaces). The
file is ignored by git, so the key never leaves your computer.

### B3a. Start it with Docker

```bash
docker build -t fixscribe .
docker run --env-file .env -p 8000:8000 fixscribe
```

The first build takes a few minutes. To also list the four finished guides on the landing, add
`-e DEMO_JOB=137c1ed0730d,7628d7064780,0e2b78efccb9,359ba5a7fa66` before `fixscribe` in the second
line.

### B3b. Or start it with Python

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m scripts.get_voice      # optional: Meta's MMS-TTS voice, else the device's voice
.venv/bin/uvicorn app.main:app
```

To also list the four finished guides, start it with
`DEMO_JOB=137c1ed0730d,7628d7064780,0e2b78efccb9,359ba5a7fa66 .venv/bin/uvicorn app.main:app`.

### B4. Use it

1. Open **http://127.0.0.1:8000** in a browser on the same computer.
2. Tap **Upload a video** and pick a repair video, up to 10 minutes. The progress page shows every
   stage; a 45-second video takes about 20 minutes, an 8.5-minute one 14 to 30 minutes.
3. **Open the guide**, then everything in [A1](#a1-a-finished-guide-1-minute) to
   [A3](#a3-the-live-coach-with-your-camera-and-voice) works the same on it.
4. The camera for the live coach works at `http://127.0.0.1:8000` on that computer. Browsers allow
   the camera only over https or on the computer itself, so for the coach on a phone use the live
   app (A).

### B5. Limits on your computer

It is not unlimited: `.env` caps what your key can spend, so a mistake never empties it. The
defaults from `.env.example`:

| Setting in `.env` | Default | What it limits |
|---|---|---|
| `MAX_VIDEO_SECONDS` | `600` | the longest video, 10 minutes |
| `DAILY_JOB_LIMIT` | `20` | videos turned into guides a day |
| `JOB_BUDGET_USD` | `10` | Meta spend for one video (a 45 s video used about $0.80) |
| `BUDGET_USD` | `120` | Meta spend in all |
| `LIVE_BUDGET_USD` | `10` | Meta spend for the live coach on one guide |
| `LIVE_MAX_CALLS` | `3000` | coach calls on one guide |

Raise any of them in `.env` and start it again. If the coach says it **reached its spend limit**
raise `LIVE_BUDGET_USD`. On a guide made from your own video the coach stops at $10 and 3000 calls.

### B6. Without a Meta key

```bash
.venv/bin/python scripts/demo_job.py
```

It builds a guide with the real pipeline and a fake Meta client, so it costs nothing, and prints a
job id: start the server (B3b) and open `http://127.0.0.1:8000/guides/<id>`. The tests run without
a key too: `.venv/bin/pytest -q`.

---

## C. Without running anything

1. Watch the **[3-minute film](https://www.youtube.com/watch?v=bpZMs6h1uUo)**: a video becoming a
   guide, then the live coach following it.
2. Open **[demo/](../demo/README.md)**: the four guides FixScribe wrote, with three photos of each
   and links to open each one in the live app.
3. In each guide's folder, `guide.json` is the whole guide, and `steps/` has every step photo, SAM
   cut-out, numbered-screw overlay and 6-second clip.
4. Scroll to **The live coach on the Dell guide** in [demo/](../demo/README.md#the-live-coach-on-the-dell-guide):
   a 29-second clip of the coach marking parts and answering, and a 30× speed-up of it following
   steps 1 to 10 on its own.

---

## If something does not work

| What you see | What to do |
|---|---|
| "Can't provide a secure connection" / "not secure" | Type the address exactly, starting with `https://`. Some school or office wifi blocks it: try mobile data. |
| The progress page stays on one stage for minutes | Normal: a 45 s video takes about 20 minutes in all. Leave the page open; it moves on by itself. |
| The coach says **Looking…** for a while | Normal: an answer takes 10 to 20 s, the marks up to a minute. Keep the camera still. |
| The camera or microphone does not start | Allow them when asked. iPhone: tap **aA** in Safari's address bar → Website Settings → Camera / Microphone → Allow. On your own computer, use `http://127.0.0.1:8000`, not the computer's network address. |
| "The coach is busy with other visitors" | Others are using the coach at the same moment. Wait a few seconds: it asks again by itself on the next frame. |
| A step shows no part marks | Several coaches were marking parts at once and that step's turn came too late. The next step gets its marks. |
| "reached its spend limit" or "spend already at budget" | On the live app, the $50 set aside for the judges' tests is used up: the [recorded clips](../demo/README.md) show the same thing. On your own computer, raise the limit in `.env` (B5). |
| `ffmpeg` not found (B3b) | Install it (B1), or use Docker (B3a). |

Every AI call goes to Meta models through the Meta Model API. The live app stops all of them at $50
in all, so the judges' tests never run past the credit.
