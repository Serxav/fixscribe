You are reviewing one step of a repair guide against the video, frame by frame.

Context: <<CONTEXT>>

The guide says:
- Instruction: <<INSTRUCTION>>
- Time: <<START>>-<<END>> s
- Main part: <<PART>>
- <<KIND>> taken out or put in: <<COUNT>>

The images are zoomed frames of this moment, in time order, numbered 1 to <<N>>. Each shows its
second in the corner. Go through them one by one, as if the video played in slow motion, and judge
only what you can see. Do not trust the guide: it can be wrong.

Answer:
- `matches`: true only if the frames show the person doing what the instruction says.
- `instruction`: if `matches` is false, one short imperative sentence of what they really do.
  Otherwise an empty string.
- `start_s`, `end_s`: the seconds where this action really begins and ends, read from the frames.
- `confidence`: from 0 to 1, for this review.
- `part_frames`: numbers of the frames where the main part is easiest to see (in view, in focus, not
  hidden by hands), best first, at most 3. Empty if it cannot be seen in any frame.
- `work_frame`, `work_x`, `work_y`: the frame where a tool tip or fingers touch the part being worked
  on, and x, y on a 0-1000 grid of that frame at the exact spot they touch. Look at the very tip of
  the tool, not at the hand. 0, 0, 0 if no frame shows it.
- `fastener_frame`, `points`: only if the guide counts any <<KIND>>. The frame where they are seen
  best, and x, y on a 0-1000 grid of that frame at the centre of each one you can see. A tool tip
  touching one spot, or fingers lifting something small from it, shows where one is. Point only at
  what you can see, at most <<COUNT>>. Otherwise 0 and an empty list.
