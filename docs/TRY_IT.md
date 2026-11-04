# Try FixScribe, step by step

**Address: https://fixscribe-wpf3.onrender.com**

It works on a phone (Safari on iPhone, Chrome on Android) or a computer. Nothing to install, no
account. It shows four finished guides with their live coach, and turns your own short repair video
into a guide (section 4). It runs on a server with 2 GB of memory that is always on, so it opens at
once.

**You can upload your own video.** MP4 or MOV, **up to 2 minutes** (30 to 60 seconds is the quickest
to try), narrated or silent. It becomes a guide in **about 20 minutes** for a 45-second video, and
**one video is processed at a time**: if another one is running, yours waits for it and then starts
by itself. Details in [section 4](#4-your-own-repair-video).

## Three ways to try it

| Way | What you need | What you get |
|---|---|---|
| **The live app** (above) | a phone or computer | the four finished guides, the live coach with camera and voice, your own video up to 2 minutes |
| **On your own computer** | Python 3.12 and ffmpeg, or Docker; a Meta Model API key; about 5 minutes to set up ([Run it locally](../README.md#run-it-locally)) | everything, with videos up to 10 minutes, no waiting for other people's videos, and Meta's own voice (MMS-TTS) reading the steps |
| **Without running anything** | a browser | the [3-minute film](https://www.youtube.com/watch?v=bpZMs6h1uUo) and [demo/](../demo/README.md): every photo, cut-out, clip and proof of the four guides, plus recorded clips of the live coach |

On your own computer the camera works at `http://127.0.0.1:8000` on that computer. From a phone,
the camera needs https, so for the coach on a phone use the live app.

## How long things take (it is slow, not stuck)

Measured on the live app on 2026-11-04. Every wait ends by itself: nothing needs a
reload.

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
who opens it. When several coaches run at once they wait for each other instead of overloading it. Close the coach tab when you
are done, so the next person does not wait for it.

## 1. A finished guide (1 minute)

1. Open the address. Under the two buttons, the landing lists **four finished guides** (a laptop, a
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

This sample guide is read-only: buttons that would change it answer "The sample guide cannot be changed."

## 2. The live coach with nothing to repair (3 minutes)

1. On the landing tap **Try the live coach**.
2. Tap **Nothing to repair right now? Use this guide's video**. The guide's own video plays where
   your camera would be.
3. Watch the panel: the coach says which step it sees (**Step 1 of 11**), its state (**On track**,
   **Step done**, **Check this**), and what comes next. The video **waits for the coach** at every frame: each answer takes 10 to 20 s.
4. When a new step starts, the parts get marked on the picture: dashed while SAM 3.1 cuts them out,
   solid once Spark has checked them. On the live app the marks take up to about a minute, and
   a mark Spark does not confirm is taken away rather than shown.
5. Type a question in **Ask about this repair…**, for example `How many screws hold the battery?`.
   The answer names its step and has a button that plays that moment of the video.
6. Buttons at the bottom: ⏸ hold the video, ‹ › previous / next step, ↻ repeat, 🔊 voice on or off,
   🎙️ talk to it.

A clip of this, recorded on 2026-11-04, is in [demo/](../demo/README.md#the-live-coach-on-the-dell-guide).

## 3. The live coach with your camera and voice

1. On the coach page tap **Start the camera** and allow the camera.
2. Point it at a laptop's underside or open back. The coach follows the Dell guide, so it shows
   **Check this** or **Looking…** when the view does not match a step.
3. Tap 🎙️ and allow the microphone. Say **"next"**, **"back"** or **"repeat"** (no AI needed), or ask
   a question out loud.

## 4. Your own repair video

On the landing tap **Record a video** (phone) or **Upload a video**. The live app takes
videos **up to 2 minutes**; a 30 to 60 second clip is the quickest to try. One video is processed at
a time: if someone else's is running, yours waits for its turn. Longer videos (up to 10 minutes) work
when FixScribe runs on your own computer ([Run it locally](../README.md#run-it-locally)).

1. Film or pick a repair or assembly video. Good light, the part filling the frame, 1080p if screws
   matter. Narrated or silent; saying "step" (or "paso") before each step cuts the steps exactly
   there.
2. The progress page shows every stage as it runs.
3. Then **Open the guide**. **Agent console** shows Muse Wonder checking the guide with SAM as a tool.

## If something does not work

| What you see | What to do |
|---|---|
| "Can't provide a secure connection" / "not secure" | Type the address exactly, starting with `https://`. Some school or office wifi blocks it: try mobile data. |
| The progress page stays on one stage for minutes | Normal: a 45 s video takes about 20 minutes in all. Leave the page open; it moves on by itself. |
| The coach says **Looking…** for a while | Normal: an answer takes 10 to 20 s, the marks up to a minute. Keep the camera still. |
| The camera or microphone does not start | Allow them when asked. iPhone: tap **aA** in Safari's address bar → Website Settings → Camera / Microphone → Allow. |
| "The coach is busy with other visitors" | Others are using the coach at the same moment. Wait a few seconds: it asks again by itself on the next frame. |
| A step shows no part marks | Several coaches were marking parts at once and that step's turn came too late. The next step gets its marks. |
| "reached its spend limit" | The Meta credit shared by all judges for this coach is used up. The [recorded clips](../demo/README.md) show the same thing. |

Every AI call goes to Meta models through the Meta Model API, with a spending cap on the server.
