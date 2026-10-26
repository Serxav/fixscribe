# Foundations audit — 2026-10-26 (night)

Question: are the **bases** strong enough to win a final judged by senior engineers on their own
phone videos? Two independent read-only audits, each backed by experiments run on this Mac:

- **Wonder** (Muse Code on `muse-wonder-1.0`, 32 calls, ≈1.72 $), prompt in `.muse-runs/audit2-prompt.md`
  (framing: "the most senior engineer in a one-million-euro final").
- **Claude Code**, same scope, without seeing Wonder's report.

Baseline: 238 tests pass (main + SAM client branch), ruff clean. Previous audit: `tasks/AUDIT.md`.

**Verdict.** The plumbing is good (job store, Meta client, retries, spend, tests harness). The
**perception layer is not**: we throw away the resolution, the colour and the true timestamps of
real phone video before any model sees it, we pick keyframes by background texture, and the
signature features (fused steps, SAM screw ledger, inspector) are not in the pipeline yet — while
the UI already claims screw verification. Nothing can be proven with numbers because there is no
eval dataset.

## Findings (cross-checked)

| # | Sev. | Found by | Evidence | Finding | Foundation fix |
|---|---|---|---|---|---|
| F1 | CRITICAL | both | MEASURED: worst error 1.3 s (Claude: 60→30 fps VFR clip; Wonder: 30→5 fps clip, +1.31 s) | Phone video is **variable frame rate**; `ingest` keeps VFR and `signals.py` stamps samples as `frame_index / fps`. | Ingest to CFR with a stated rate (`-fps_mode cfr -r 30`); every reader stamps frames with real PTS (`CAP_PROP_POS_MSEC`). |
| F2 | CRITICAL | both | MEASURED: iPhone-style HLG/BT.2020 10-bit → 8-bit still tagged BT.2020; −25 % saturation as decoded by OpenCV (Claude); no tone mapping, mislabelled output (Wonder). `zscale` is **not** in our ffmpeg build. | HDR footage reaches Spark, SAM and keyframes with wrong colour and clipped highlights. | `probe()` reads `color_transfer`/`color_primaries`; ingest converts HLG/PQ BT.2020 → BT.709 SDR with the filters we do have (`colorspace`, `tonemap` via a linear path, or VideoToolbox), tags BT.709, and a 10-bit HLG fixture proves it. |
| F3 | CRITICAL | both | MEASURED: 1.2 mm screw head ≈ 4 px (Claude, 25 cm framing) / 5.8 px (Wonder, 150 mm framing) at 720p | Ingest downsizes to 720 p, keyframes come from that proxy, SAM caps at 1280 px. Screws are a few pixels. | **Two ladders**: a light proxy for Spark/ASR, and the **native original** for keyframes and SAM; SAM gets 2–3× upscaled **crops** around the part, not whole frames. |
| F4 | CRITICAL | both | MEASURED: whole-frame Laplacian prefers a blurred part on a busy mat 69,704 vs 197 (Claude) / 47,512 vs 17 (Wonder); on the part only it is right (1,078 vs 321) | Keyframe sharpness measures background texture, glare and subtitles, not the part. | ROI sharpness (part box or centre crop) × steadiness (low motion from `signals.json`) − hand coverage; keep top-5 for the SAM rerank. |
| F5 | CRITICAL | Wonder | CODE `assembly.py:95,154`, `guide.html:76` | The screw check compares Spark's count with a deep copy of itself; the UI then says **"Every screw goes back"**. A false safety claim. | Until SAM counts independently, show "count from the video analysis, not verified"; the green banner requires an independent SAM count. |
| F6 | CRITICAL | both | CODE: `segment.py`, `inspector.py`, `fusion.py` absent/empty; `signals.py`, `overlay.py` not wired | Today the product is one Spark call + cleanup. The three "unexpected capabilities" are not in the pipeline. | Build one **vertical slice** end to end (signals → fusion → segment/ledger on one step → overlay) before more surface work. |
| F7 | CRITICAL | both | MEASURED: zero labelled videos, zero eval runs | `eval/score.py` has no dataset, no runner, no recorded number; nothing measures SAM, keyframes or cost. | 5 labelled phone videos (narrated, silent, VFR, HDR, close-up screws) + one command writing a dated JSON (step F1, ±2 s boundaries, screw accuracy, SAM IoU, keyframe check, seconds and dollars per stage). |
| F8 | HIGH | both | CODE `frames.py:134`, `guide.py:102`; 10 copies of JSON read/write helpers | Stages overwrite each other's files (frames rewrites `guide.json`); only `guide`/`analysis`/`status` are typed; no version, input hash, cache or per-stage timing. "Regenerate one step" is impossible. | Typed model for every artifact, one `app/artifacts.py` load/save, each stage owns its file, one **assemble** stage builds `guide.json`, `manifest.json` with `{stage, version, input_sha256, seconds, usd}`, cache by hash. |
| F9 | HIGH | Wonder | CODE `scenes.py:19,99` | A voice cut is the **start of the ASR turn** (can be a whole sentence early); one keyword ⇒ `source="none"` and is discarded; the part before the first keyword is ignored. | Cuts become intervals `[turn_start, turn_end]` with uncertainty; single cuts are valid hints; add the pre-first-cut range. |
| F10 | HIGH | both | MEASURED: false pause at 3.4 s on constant, accelerating motion (Wonder); CODE: runs detected on raw values, not the smoothed curve | Relative 35th-percentile threshold invents pauses; camera shake sets the motion floor. | Smoothed curve, absolute + relative threshold, global-motion (camera shake) compensation; must pass a handheld-shake fixture before it can move a boundary. |
| F11 | HIGH | both | CODE `analyze.py:120`, `guide.py:23`; Spark's video sampling rate is not documented | LLM video timestamps are the least reliable output and the only source of step times. | Fusion (snap to voice/visual candidates) + Spark pass 2 on short clips for uncertain steps; experiment: burn a timecode into the Spark proxy with OpenCV (our ffmpeg has no `drawtext`) and measure the gain on the eval set. |
| F12 | HIGH | both | MEASURED: no rotation/VFR/HDR/60 fps/shake/tiny-screw fixture in 238 tests | The suite proves plumbing, not physics. The first real iPhone video is the first real test. | Fixture factory (ffmpeg-generated: rotated, VFR, 10-bit HLG, 60 fps, shaky) + one behavioural assertion per stage. |
| F13 | MEDIUM | Wonder | MEASURED: marker disc ≥ 28 px on a ~6 px screw | `draw_screws` hides the screw it labels; it assumes display pixels (no `size_sent`), so it will misalign with crops. | Ring + leader line sized to the box; same scaling contract as `draw_part`. |
| F14 | MEDIUM | both | CODE `meta_client.segment`, `frames.key_moment` | SAM always gets the whole downscaled frame, no confidence filter, no NMS; concepts like "battery connector bracket" are long phrases; keyframe window = ±1 s around one LLM evidence time; no SAM call budget. | Crops + confidence threshold + duplicate suppression; short head-noun concepts with fallbacks; keyframe search over the whole step; SAM calls counted in the job budget. |
| F15 | MEDIUM | Wonder | MEASURED: 60 fps proxy ≈ 250 MB per 10 min; 16k output tokens may truncate long videos | No decision on proxy fps/resolution for Spark; no chunking; no per-stage timing; per-job budget not merged yet. | Proxy rate chosen by an eval experiment; chunk videos > ~120 s; per-stage time and spend in the manifest; merge task 017 (job budget). |
| F16 | MEDIUM | Wonder | CODE `guide.py:56`, `frames.py:155` | Evidence kept outside the step; clamps/shifts not logged; review only from Spark's self-confidence; keyframe JPEG not atomic; clips re-encoded at CRF 28 from a CRF 23 proxy. | Evidence ∈ [start, end]; every shift logged in checks; review from signal agreement; atomic stills; clips cut from the best source at CRF ≤ 20. |
| F17 | MEDIUM | Claude | REASONING | The same video re-uploads and re-pays on every run. | Cache Files API ids and stage outputs by video SHA-256. |

## Already solid (keep)
- Rotation tags: MEASURED by both — a 1920×1080 file tagged 90° becomes a correct 720×1280 portrait.
- Seeking in long-GOP H.264: MEASURED — ≈3 ms error, 0.16 s per step; signals ≈12 s per 10 min.
- `meta_client` as the single Meta door (spend log, capped Retry-After, no paid-timeout retries,
  official SAM parser), job store discipline, safe job ids, network-blocked tests.

## Foundation plan (order matters; one task each, all with fixtures and numbers)
1. **Media ladder** — CFR + PTS timestamps, HDR→SDR, native original kept for stills, proxy rate
   decided; fixture factory (F1, F2, F3, F12, F15).
2. **Artifacts** — typed models for every file, one IO module, stage-owned files, `assemble` stage,
   `manifest.json` with version/hash/time/cost, cache (F8, F17).
3. **Honest screw claim** — remove the false "Every screw goes back" until SAM verifies (F5). Small, now.
4. **Signals v2** — smoothed pauses, shake compensation, voice cut intervals (F9, F10).
5. **Fusion + Spark pass 2** — boundary sources and agreement confidence; timecode experiment (F11, F16).
6. **Perception** — ROI keyframe scoring; SAM on native crops with confidence/NMS; screw ledger
   before/after; overlay rings (F3, F4, F13, F14). This is the vertical slice of F6.
7. **Eval** — 5 labelled videos and one-command metrics, run after every foundation task (F7).
8. **Inspector** (Wonder agent) only after 1–7, on steps where the checks disagree.

Pending branches: `feat/web-v2` (task 011, 8 review points) and `feat/sam-client` (task 014, unreviewed;
its overlay needs F13 before merge). The web second round waits until the foundations above exist,
so the UI shows real verified data instead of claims.
