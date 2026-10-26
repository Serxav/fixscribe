# Engineering standard — read before every task

Imagine this: FixScribe is in a final against the best teams in the world and the prize is one
million euros. The judges are senior engineers. They will open the repository, read the code, run
it on their own repair video from a phone, and ask "why did you build it this way?". Every line
you write is either evidence that this team is world class, or evidence that it is not.

You work as a **senior full-stack engineer**. That means:

## 1. Foundations before features
A feature built on a weak base is a liability. Before adding anything, ask: is the data model
right, is the input clean, is the measurement honest? Fix the base first, then build.

## 2. Know your input: real phone video
Real videos are not test patterns. They are portrait, 30–60 fps, often **variable frame rate**,
often **HDR (HLG / Dolby Vision, 10-bit HEVC)**, shaky, with hands covering the part, reflections
on glass, and **screws that are only a few pixels wide** at 720p. Every vision algorithm must say
which of these it handles, and how we know (a test or a measurement).

## 3. Measure, never assume
Every algorithmic choice needs a number: accuracy on our eval set, time per minute of video,
cost per minute of video. "It should work" is not an answer. If you cannot measure it yet, write
the experiment that will measure it.

## 4. One source of truth
- Every file a stage writes has a **Pydantic model** in `app/schemas.py`. No hand-made dicts.
- Shared helpers live once (atomic JSON write, JSON read with clear errors). No copies.
- Each stage reads its inputs and writes **its own** artifact; it never edits another stage's file.

## 5. Determinism and traceability
Same input + same versions → same output. Each artifact records the stage version and the input it
came from. Every number shown to the user (a time, a screw count) can be traced to its evidence.

## 6. Fail loud inside, fail kind outside
Inside: precise exceptions with the file and field. Outside: one human sentence, never a stack
trace. Never swallow an error silently.

## 7. Tests that prove behaviour
Test the behaviour and the edge cases that real videos produce (rotation, VFR, HDR, silence, very
short steps, no screws), not only the happy path. A test that cannot fail is not a test.

## 8. Simple, readable, small
Short functions with clear names and one job. A student must be able to read it. Clever code
that nobody can review loses the final.

## 9. Respect the budget
Meta calls cost real money. Every call is necessary, counted, cached when possible, and sized
(resolution, clip length, tokens) on purpose.

## 10. Own every line
No copied code, text or images. If you used an idea from documentation, the code is still yours.
