# FixScribe algorithm v2 — many signals, cross-checked

v1 asks Muse Spark once for everything. That is fragile: one model call decides the step times,
the parts and the screw counts, and nothing checks it. v2 treats each Meta model as one **signal**,
adds cheap local signals (OpenCV, ffmpeg), and **fuses and verifies** them. Every step in the final
guide says where its evidence comes from and how sure we are.

```
            ┌─ voice turns (Muse Voice)  ──► voice cuts ───────────┐
video ──────┼─ motion / scene signal (OpenCV) ──► visual cuts ─────┼─► boundary fusion ─► steps
            └─ Muse Spark pass 1 (whole video) ──► draft steps ────┘          │
                                                                              ▼
                        Muse Spark pass 2 (one clip per uncertain step) ─► refined step
                                                                              │
     SAM 3.1: part mask · fasteners propose→choose→follow→decide ─► fastener ledger,
                                                                         keyframe, overlay
                                                                              │
                        checks ─► Muse Wonder inspector (tools: segment, set_keyframe,
                                  update_step) only where a check failed
                                                                              ▼
                                                     guide.json + eval metrics + cost
```

## 1. Signals
| Signal | Source | Output | Strength |
|---|---|---|---|
| Voice cuts | `transcribe` turns with "step"/"paso" | `scenes.json` cuts | exact when the technician narrates |
| Visual cuts | OpenCV at 4 fps on a 160 px gray proxy: frame-difference **motion energy** and color-histogram **scene change** | `signals.json`: motion curve, pauses, scene changes, ranked candidate boundaries | works on silent videos; hands stop between actions |
| Draft steps | Spark pass 1 on the whole video, with voice and visual candidates as hints | `analysis.json` | understands actions and parts |
| Refined step | Spark pass 2 on a short clip of one step (±2 s) | per-step fields | precise times, screw count, warnings |
| Part mask | SAM 3.1 concept = target part, on the keyframe | box + mask, overlay image | shows *what* to touch |
| Fasteners | SAM 3.1 sliced search on the step clip, Spark picks by number, SAM video follows | tracks | counts and locates fasteners put in / taken out |
| Hand occlusion | SAM 3.1 concept "hand" on keyframe candidates | boxes | picks a frame where the part is visible |

## 2. Boundary fusion (pure logic, `app/pipeline/fusion.py`)
For each boundary proposed by Spark, snap it to the strongest candidate within ±1.5 s:
voice cut (weight 1.0) > visual pause (0.6) > scene change (0.4). Keep Spark's time when nothing is
close. Record `boundary_source` per step and raise or lower confidence:
`confidence = spark_confidence × agreement`, where agreement is 1.0 when voice and vision agree,
0.8 with one signal, 0.6 with Spark alone. Steps below 0.5 go to pass 2 and are marked "Check this step".

## 3. Fastener ledger (`app/pipeline/fasteners.py`)
Comparing one frame before and one after a step fails on hand-held video (the camera moves, a hand
covers the part, the light changes), and asking a language model for coordinates of a few-pixel
screw gives boxes beside it. The method follows what works in the literature instead:
1. **Propose (sliced inference, SAHI).** The step clip is cut from the original upload at up to
   1080p (the 720p working copy is too small for a screw). On two sharp frames of the step's end
   (start, when taking apart) SAM 3.1 searches every fastener word the step names on the whole
   frame and on four overlapping enlarged quarters. Weak and oversized boxes are dropped.
2. **Follow (SAM 3.1 video, zoomed).** Every candidate is followed through the whole step clip
   (at most 120 frames, 2–10 fps), on a copy cropped and enlarged around the work area: small
   objects are tracked far better when they are bigger.
3. **Decide (votes over time).** A candidate stays only if it is seen in at least half the frames
   of its end of the step and in at least half more of them than at the other end: put in when
   building, taken out when taking apart. Two tracks on one fastener are merged.
4. **Choose (set-of-mark prompting, several views).** Muse Spark sees each remaining candidate
   numbered, on up to three frames of the video (one image per candidate), and answers which
   numbers really are that fastener. It never gives coordinates. Never more than the analysis
   counted.
A fastener the video does not clearly show is never invented; the step keeps the analysis count and
says how many were seen, and the guide warns when the video is below 1080p. Each kept fastener gets a
numbered marker S1, S2, … drawn on the frame of its end that shows the most of them; the motion
stage draws the same tracks on its clip. Reassembly uses the ledger in reverse. The method is
measured with `python -m eval.video_score` against fastener positions marked by hand on frames of
a real video (`eval/video_key.json`).

## 4. Keyframe v2
Candidates = top 5 sharpest frames in the window. Rerank with SAM: prefer the frame where the target
part box is large and the hand boxes overlap it least.

## 5. Inspector (Muse Wonder, agentic)
Runs only on steps that failed a check (max 5 steps, max 6 tool calls each). Tools:
`segment(step, concept, t)`, `set_keyframe(step, t)`, `update_step(step, fields)`. Every tool call
is logged in `guide.inspector_log` and shown in the UI as "Verified by the inspector".

## 6. Cost and latency control
- Per-job budget (default 1 $) on top of the global budget; a job stops cleanly when it would pass it.
- Spark pass 2 only for uncertain steps or steps with screws; SAM only on 2–3 frames per step.
- Cache by video SHA-256: the same video never pays twice.
- Measure, don't guess: the effect of a lower-resolution proxy on Spark tokens is an experiment
  in `eval/`, not an assumption.

## 7. Evaluation (technical depth)
`eval/` keeps a small dataset (`samples/*.mp4` + `*.expected.json`) and writes one JSON per run:
step F1, mean IoU, boundaries within ±2 s, screw count accuracy, cost per minute of video,
latency per stage, prompt version. A table in the README compares v1 (Spark only) with v2 (fusion).
