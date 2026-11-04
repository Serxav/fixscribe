# Try FixScribe, step by step

There are three ways to try it. Each one is explained step by step below.

| Way | What you need | What you get | Set-up |
|---|---|---|---|
| [**A. The live app**](#a-the-live-app) | a phone or computer | the four finished guides, and the live coach with the guide's video, your camera and your voice | none |
| [**B. Your own video, on your computer**](#b-your-own-video-on-your-computer) | Docker and a Meta Model API key | a guide from your own video (up to 10 minutes), its live coach, and Meta's MMS-TTS voice | about 10 minutes |
| [**C. Without running anything**](#c-without-running-anything) | a browser | the 3-minute film, and every photo, cut-out, clip and proof of the four guides, plus recorded clips of the live coach | none |

The live app runs on a free server with 512 MB of memory: enough for the guides and the live coach,
not for turning a new video into a guide (that needs about 690 MB). So your own video runs on your
computer (B).

---

## A. The live app

**Address: https://fixscribe-wpf3.onrender.com**

It works on a phone (Safari on iPhone, Chrome on Android) or a computer. Nothing to install, no
account. **If nobody opened it in the last 15 minutes, the first visit takes about 1 minute** while
the free server wakes up; after that pages open at once.

**Meta credit for your tests: about €55 is left (2026-11-04).** It is shared by all the judges and
pays for every AI call on the live app: the live coach and questions. To protect it, the live app
stops every Meta call once it has spent **$50 in all**; after that it answers that it reached its
spend limit. If it does stop, ways B and C still work.

### How long things take (it is slow, not stuck)

Measured on the live app on 2026-11-04. Every wait ends by itself: nothing needs a reload.

| What | How long | What you see meanwhile |
|---|---|---|
| Opening the app after 15 quiet minutes | **about 1 minute** | a loading page while the free server wakes up |
| Opening the app otherwise | **at once** | |
| Opening a guide, its photos and clips | under 1 s | |
| The coach's first answer, and each new one | **10 to 20 s** | **Looking…**; with the guide's video, the video pauses until the answer comes |
| The part marks on a new step | **up to about 1 minute** | the step and its instruction are already shown; the marks appear dashed, then solid (or go away if Spark does not confirm them) |
| A typed or spoken question | **5 to 10 s** | **Thinking…**, then the answer and a button to that moment of the video |
| The coach following a whole guide with its video | **about 15 to 20 minutes** for 11 steps | the step changes on its own; a 30× speed-up is in [demo/](../demo/README.md#the-live-coach-on-the-dell-guide) |
| Several people using the coach at the same moment | **a little longer** | the server is shared, so coaches take turns: part marks are worked out one at a time, answers three at a time. A step whose marks waited too long shows none; the next step gets them |
| Turning your video into a guide (on your computer, B) | **about 20 minutes** for a 45 s video | a progress page with every stage as it runs |

**One coach per judge at a time works best.** The live app runs on one server shared by everyone
who opens it. When several coaches run at once they wait for each other instead of overloading it.
Close the coach tab when you are done, so the next person does not wait for it.

### A1. A finished guide (1 minute)

1. Open the address. Under the buttons, the landing lists **four finished guides** (a laptop, a
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

The coach is made for following a guide while you repair. On the live app, try it with a finished
guide's own video:

1. On the landing tap **Try the live coach** (or **live coach** next to any guide in the list).
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
2. Point it at the object of that guide: a laptop's underside on the Dell guide, or your own object
   on a guide made from your own video (B). It shows **Check this** or **Looking…** when the view does not
   match a step.
3. Tap 🎙️ and allow the microphone. Say **"next"**, **"back"** or **"repeat"** (no AI needed), or ask
   a question out loud.

### A4. Your own repair video

On your computer: way B, just below.

---

## B. Your own video, on your computer

Everything runs on your machine; only the AI calls go to Meta's servers, paid by your own Meta key.
Videos can be up to 10 minutes, nobody else's video is ahead of yours, and the steps are read aloud
with Meta's MMS-TTS voice.

### Quick start (Docker, about 10 minutes)

1. Install **Docker Desktop** (docker.com) and start it.
2. In a terminal:

   ```bash
   git clone https://github.com/Serxav/fixscribe.git && cd fixscribe
   cp .env.example .env
   ```

3. Open the file `.env` in any text editor and paste your Meta Model API key after `MODEL_API_KEY=`
   (no quotes, no spaces). Save it.
4. Back in the terminal (the first build takes a few minutes):

   ```bash
   docker build -t fixscribe . && docker run --env-file .env -p 8000:8000 fixscribe
   ```

5. Open **http://127.0.0.1:8000**, tap **Upload a video** and pick a repair or assembly video, up to
   10 minutes, narrated or silent. A 45-second video becomes a guide in about 20 minutes; the
   progress page shows every stage, so leave it open.
6. **Open the guide**, then **Live coach** → **Start the camera**, and point the camera at your object:
   the coach follows you through your own guide. The camera works on this computer at
   `http://127.0.0.1:8000`.

The sections below give the same steps in more detail, and the way without Docker.

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
