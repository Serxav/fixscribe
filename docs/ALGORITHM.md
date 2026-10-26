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
             SAM 3.1: part mask · screws before/after · hand occlusion ─► screw ledger,
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
| Screws before/after | SAM 3.1 concept "screw" on a frame just before and just after the step | boxes | counts and locates removed screws |
| Hand occlusion | SAM 3.1 concept "hand" on keyframe candidates | boxes | picks a frame where the part is visible |

## 2. Boundary fusion (pure logic, `app/pipeline/fusion.py`)
For each boundary proposed by Spark, snap it to the strongest candidate within ±1.5 s:
voice cut (weight 1.0) > visual pause (0.6) > scene change (0.4). Keep Spark's time when nothing is
close. Record `boundary_source` per step and raise or lower confidence:
`confidence = spark_confidence × agreement`, where agreement is 1.0 when voice and vision agree,
0.8 with one signal, 0.6 with Spark alone. Steps below 0.5 go to pass 2 and are marked "Check this step".

## 3. Screw ledger (the screw counter and verifier)
1. For a step with screws, take a frame ~0.5 s **before** it starts and ~0.5 s **after** it ends.
2. SAM "screw" on both. A screw present before and missing after (no box within 4 % of the frame
   diagonal) was **removed in this step**. Its box becomes a numbered marker S1, S2, … on the map.
3. Each removed screw gets an identity: `{id, step, position (normalized), size_class}`; `size_class`
   comes from the box area relative to the others (short/long screws are a real cause of damage).
4. Count check: Spark count vs SAM count. Disagreement → check + inspector.
5. Reassembly uses the ledger in reverse: "Screw S3 (long) goes back at position 3 of the back cover".
   The UI keeps a **screw tray**: screws land in it when a step is done and leave it when they go back.

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
