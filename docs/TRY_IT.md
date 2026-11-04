# Try FixScribe, step by step

**Address: https://fixscribe-wpf3.onrender.com**

It works on a phone (Safari on iPhone, Chrome on Android) or a computer. Nothing to install, no
account. It shows a finished guide and its live coach; making a guide from your own video runs on
your computer (section 4). It runs on a free server: the **first visit can take about a minute** while it wakes up.

## 1. A finished guide (1 minute)

1. Open the address and tap **See a finished guide**. It is the guide FixScribe wrote from a
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
   solid once Spark has checked them.
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

The free server behind the live app is too small to turn a new video into a guide (the pipeline
needs more than its 512 MB), so the upload buttons are off there. To try it on your own video, run
FixScribe on a computer with a Meta key ([Run it locally](../README.md#run-it-locally), about
5 minutes to set up), or see [four guides it made](../demo/README.md) from real repair videos:

1. Upload a repair or assembly video, up to 10 minutes. Good light, the part filling the frame,
   1080p if screws matter. Narrated or silent; saying "step" (or "paso") before each step cuts the
   steps exactly there.
2. The progress page shows every stage as it runs.
3. Then **Open the guide**. **Agent console** shows Muse Wonder checking the guide with SAM as a tool.

## If something does not work

| What you see | What to do |
|---|---|
| "Can't provide a secure connection" / "not secure" | Type the address exactly, starting with `https://`. Some school or office wifi blocks it: try mobile data. |
| The page takes long to open | The free server is waking up. Wait a minute and reload. |
| The camera or microphone does not start | Allow them when asked. iPhone: tap **aA** in Safari's address bar → Website Settings → Camera / Microphone → Allow. |
| "reached its spend limit" | The Meta credit shared by all judges for this coach is used up. The [recorded clips](../demo/README.md) show the same thing. |

Every AI call goes to Meta models through the Meta Model API, with a spending cap on the server.
