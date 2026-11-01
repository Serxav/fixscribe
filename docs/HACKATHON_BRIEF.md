# Hackathon brief (read before every task)

## What we build and for whom
FixScribe turns a phone video of a repair into a step-by-step guide. Users: repair technicians
and shops. A technician films one repair (narrated or silent) and gets a guide that a colleague
or a customer can follow: steps, warnings, the part highlighted, a numbered screw map, a short
clip per step, the reverse reassembly guide and a check that every screw goes back.

## How we are judged (Meta Global AI Developer Hackathon, Indie track)
| Criterion | Weight | What it means for FixScribe |
|---|---|---|
| Impact | 30 % | A real technician problem, solved from the phone. Works on a real repair video, not only on test clips. Feedback from real technicians. |
| Use of Meta AI tooling | 25 % | Creative use beyond a basic API call (see "unexpected capabilities"). Built with Muse Code: our `tasks/` folder is the proof. |
| Technical depth | 20 % | Solid engineering: tests that mock Meta, atomic job files, retries, a spend counter, and **evaluation with numbers** (`eval/`). |
| Demo | 25 % | A live demo that does not break, and a 3-minute video. Every feature must be easy to *see*. |

## Our unexpected capabilities (say them, show them)
1. **SAM 3.1 as a screw counter and verifier**: it segments every screw, numbers them on a map
   and checks that the same screws go back in the reassembly.
2. **Muse Voice Transcribe turns as step cuts**: the moments where the technician says
   "step" / "paso" split the video into steps.
3. **Muse Wonder as an inspector agent** that uses SAM as a tool to check and fix its own steps.

## Extra prizes we aim for
- **Best Agentic Use-Case**: the inspector (autonomy, effectiveness, usefulness).
- **Best Creative Build**: requires Muse Image or Muse Wonder.

## Rules that disqualify or hurt us
- Only new work written from Oct 26, 2026. Never copy code from other projects.
- Meta models only inside the product, always through `app/meta_client.py` (the voice is Meta's open-weights MMS-TTS, run locally in `app/voice.py`).
- No Streamlit. Web app = FastAPI + Jinja2 + Tailwind CDN + plain JavaScript.
- Never invent endpoints, fields or model IDs. Never leak keys.

## Five questions before you say a task is done
1. **Does it work in the demo, from a phone?** (real video, mobile screen, no hidden setup)
2. **Does it fail gracefully?** (clear message, the job does not crash, no traceback for the user)
3. **Will it be clear in the 3-minute video?** (can a judge see what it does in a few seconds?)
4. **Is it tested?** (normal case and at least one failure, Meta mocked)
5. **Does it use the Meta model well?** (right model, right fields from the docs, no wasted calls)
