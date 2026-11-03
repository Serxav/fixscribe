# Demo film

About 3:30, built in code (React with Remotion, rendered frame by frame) around the product's own
output: every frame, SAM outline, clip, page capture, score and file shown comes from a real job or
from the repository. Narration is one English voice; the music and sound are synthesized in code.

Rules: one beat on screen at a time (it leaves before the next one enters), real video wherever it
can be, and no number that is not in the README.

| # | Scene | What is shown |
|---|---|---|
| 1 | What it is | The name, then three panels: you film the repair → FixScribe writes the guide → it coaches you live |
| 2 | The problem | A manual with the one page nobody wrote; the hands of someone who knows |
| 3 | Film it | The real repair video, full frame, then inside a phone |
| 4 | Seventeen stages | Every pipeline stage with its model (Meta model, code or rules) and this video's real seconds and cost |
| 5 | Listen, watch, refuse | Muse Voice cuts on the spoken steps · Spark writes the steps from the whole video · the safety rules refuse professional-only jobs |
| 6 | Point and cut | Spark points at the part, SAM 3.1 cuts it out of that exact frame, then SAM video follows it |
| 7 | Any object | The 20 exam photos with their real marks; one domain file per kind of object |
| 8 | Watch it happen | Each step's loop clip; "Watch step N" opens the original video at that second |
| 9 | The guide | The real guide page scrolled in a phone (parts and steps; no score shown) |
| 10 | The way back | Reverse order and the fastener tally |
| 11 | Live coach · which step | A camera frame plus the guide's photos of the steps around it go to Spark; one odd frame never moves it. The screen recording of the coach goes here |
| 12 | Live coach · the marks | Spark points, SAM cuts (dashed), Spark checks (solid) |
| 13 | Live coach · voice | Next / back / repeat with no model; a question goes to Spark and plays its moment; ~8 s an answer, ~20 s the marks |
| 14 | The answers first | The hand-placed answer key on a photo, the model's marks, found and missed |
| 15 | Measure again | Recall 0.83 → 0.89, precision 0.98 → 1.00 on 20 photos, with the warning that live marks are right 89 % and 74 % of the time; the coach's own part 7 → 10 of 11 |
| 16 | What to look for | A domain file typed out |
| 17 | Try to break it | Strange model answers and what each one becomes; 959 tests |
| 18 | One job per model | Spark, SAM 3.1, Muse Voice, Muse Wonder; the name |

## To film by hand

- The live coach on the deployed address, from a phone, about 25 seconds in one take: the camera on
  the object, a step change, marks going from dashed to solid, "next" said aloud.

## Before the final render

- Run the final repair video through the pipeline and use that job (`collect3.py` in the film's
  working folder), so every frame and number in the film is from the video being submitted.
- Use only a video you have the right to publish. Keep faces, documents and other people's footage
  out of the frame.
