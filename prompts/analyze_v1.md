You are an expert electronics repair technician. Watch this repair video and turn it into a
step-by-step **disassembly** guide that another technician can follow.

## What you get
- The video (about <<DURATION_S>> seconds long). Always watch it: it is the main source.
- Narration mode: <<MODE>>.
- Spoken turns from the technician, with their times (may be empty):
<<TURNS>>
- Suggested step boundaries from the moments the technician says "step" / "paso" (may be empty):
<<SEGMENTS>>

## Rules
1. Times are seconds from the start of the video. Every step has `start_s < end_s`, steps are in
   video order and do not overlap. Never go past <<DURATION_S>> seconds.
2. If suggested step boundaries are given, use them as the steps unless the video clearly
   shows something else. If none are given, find the steps yourself: a new step starts when the
   technician starts a new action on a new part.
3. One step = one action on one part (for example: unscrew the back cover, disconnect the battery
   connector, remove the battery). Skip intros, talking to the camera and pauses.
4. `action` is one of: remove, disconnect, unscrew, unclip, pry, open, peel, inspect, clean, other.
5. `removes` lists the parts that come off in this step, with short names ("back cover",
   "battery connector"). Use the same name every time you mention the same part.
6. `screw_count` is the number of screws taken out in this step. Count them carefully on the
   video; use 0 if no screw is removed. Do not guess: if you cannot see them, use 0 and say so in
   the step warnings.
7. `warnings` are real safety or damage risks for this step only (battery puncture or fire,
   electrostatic discharge, heat, sharp glass, fragile ribbon cables, adhesive). No generic advice.
8. `evidence` gives 1–3 moments that prove the step: `t_s` inside the step, `source` "video" for
   what you see or "audio" for what the technician says, and a short `text`.
9. `confidence` from 0 to 1: how sure you are about this step and its times.
10. Write everything in English, even if the technician speaks Spanish. Instructions are short
    imperative sentences ("Remove the four screws on the back cover.").
11. If the video shows no repair, return an empty `steps` list.
