You are an expert technician. Watch this video and write a step-by-step <<GUIDE_KIND>> guide
that another person can follow. Describe exactly what the person in the video does, in the order
they do it. Never describe the opposite of what you see: if they put a part on, the step puts it
on; if they take it off, the step takes it off.

## What you get
- The video (about <<DURATION_S>> seconds long). Always watch it: it is the main source.
- Narration mode: <<MODE>>.
- What the person says, with times (may be empty). When they narrate, their words are the best
  description of each step: follow them.
<<TURNS>>
- Suggested step boundaries from the moments the person says "step" / "paso" (may be empty):
<<SEGMENTS>>

## What the video shows
<<DOMAIN>>
Task: <<TASK_SENTENCE>>

## Rules
1. Times are seconds from the start of the video. Every step has `start_s < end_s`, steps are in
   video order and do not overlap. Never go past <<DURATION_S>> seconds.
2. If suggested step boundaries are given, use them unless the video clearly shows something
   else. Otherwise a new step starts when the person starts a new action on a new part. When the
   person narrates, a step usually starts when they announce it ("ahora cogeremos…", "now we…").
3. One step = one action on one part. Skip intros, talking to the camera and pauses.
4. `action` is one of: <<ACTIONS>>. Choose the verb of what the person really does.
5. `removes` lists the parts handled in this step (taken off, or added when building), with
   short names. Use the same name every time you mention the same part.
6. `target_part` is the main part of the step, as the person would call it.
   `sam_concept` is 1-3 common English words for that same part, as it looks on screen, that an
   image model can find: a simple noun, no letters or codes ("wooden leg", "metal bolt",
   "table top", "back cover", "drain hose"). Never "rail c" or "part 3". Never a tool, a bottle,
   a hand or anything else that is only being used on the part.
7. `screw_count` is the number of fasteners (screws, bolts, nuts, dowels, clips... see above)
   <<FASTENER_VERB>> in this step. Count them on the video, or take the number the person says
   ("doce tornillos" = 12). Use 0 if none.
   `fastener_s` is the second inside the step where those fasteners are seen best: when the
   person points at them, says where they go ("en estos cuatro agujeros"), or the last moment
   they are all in view. `fastener_where` says where they are in a few English words, as the
   person describes it or as you see it ("four holes along the middle rail", "two corners of
   the back cover"). Use 0 and "" when `screw_count` is 0.
8. `warnings` are real safety or damage risks for this step only. No generic advice.
9. `evidence` gives 1–3 moments that prove the step: `t_s` inside the step, `source` "audio" with
   the person's own words (quote them, in their language) or "video" with what you see.
   Every step needs at least one piece of evidence; when the person narrates, one must be "audio".
10. `confidence` from 0 to 1: how sure you are about this step and its times.
11. Write titles and instructions in English, as short imperative sentences that match what the
    person does ("Insert two short dowels into the top holes of each side rail.").
12. If the video shows no repair or assembly, return an empty `steps` list.
