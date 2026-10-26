# FixScribe design v2 — "Workbench"

FixScribe is a tool used **during** a repair, phone propped next to the device, hands busy. It must
feel like a precision instrument: calm, exact, legible from 50 cm, distinctive. Not a template.

## Identity
- **Motif:** the technician's magnetic screw mat. A faint 8 px grid behind media, numbered round
  screw markers (S1, S2…) in a monospaced face, a **screw tray** that fills and empties.
- **Dark first** (workshops, OLED phones), with a full light theme.
- **Signal color:** lime `#D4FF3A` on graphite. Used only for the primary action, progress and
  "verified". Nothing else is lime.

## Tokens
| Token | Dark | Light |
|---|---|---|
| `--bg` | `#0E0F11` | `#F6F6F3` |
| `--surface` | `#16171A` | `#FFFFFF` |
| `--raised` | `#1F2125` | `#EFEFEB` |
| `--line` | `rgba(255,255,255,.08)` | `rgba(0,0,0,.08)` |
| `--text` | `#F2F3F5` | `#111214` |
| `--muted` | `#9A9DA4` | `#5F6268` |
| `--signal` | `#D4FF3A` (text on it `#0E0F11`) | `#5B7A00` (text on it `#FFFFFF`) |
| `--warn` | `#FFB020` | `#9A5B00` |
| `--danger` | `#FF5A4E` | `#C2261B` |

- **Type:** UI `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", system-ui, sans-serif`;
  numbers, timecodes and screw ids `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace`
  with tabular figures. Scale: 40/44 display, 28/32 title, 20/26 step title, 17/24 body,
  15/20 secondary, 12/16 label (uppercase, +0.06em tracking).
- **Space:** 4 px base; 16 px phone gutters; sections 32 px apart. Radius 16 px (cards), 12 px
  (media), 999 px (pills, buttons).
- **Elevation:** no drop shadows in dark; 1 px `--line` borders. Light: one soft shadow for sheets only.
- **Motion:** 160–240 ms, ease-out, only to explain change (step slide, tray fill, progress). Respect
  `prefers-reduced-motion`.
- **Touch:** primary actions in the bottom thumb zone, ≥ 56 px high; everything ≥ 48 px.
- **Icons:** own inline SVG, 1.75 px stroke, 24 px grid. No emoji. No brand logos except
  "by Meta" in plain text where we credit the models.

## Screens
1. **Home** — one job: start a repair. Big round **Record** button (camera shutter metaphor,
   lime ring) that opens the camera (`capture="environment"`), a quiet "Upload a video" link
   (custom styled, never the native file control), and an **example guide** card (keyframe
   thumbnails + "5 steps · 5 screws") that opens a sample. Three one-line promises with icons:
   *Watches the video · Hears your narration · Counts every screw*.
2. **Processing** — a live **workbench**: the video timeline as a bar; as stages finish, real
   artifacts appear on it: duration and resolution, transcript snippets at their times, cut markers
   (voice = lime, visual = gray), step titles, then keyframe thumbnails. Human stage labels, an
   honest time estimate, never the raw job id or "done".
3. **Guide overview** — first screen: a contact sheet of keyframes (portrait), title, one meta
   line (`5 steps · ~25 min · 5 screws · Medium`), tools as a row with an edge fade, and one primary
   button **Start repair**. Then the **step timeline** (segments per step, voice-cut markers), the
   compact step list, safety notes as a calm inline note (icon + text, warn color only on the
   icon and title), and **Put back** with the screw check.
4. **Repair mode** — one step per screen, full-bleed portrait media (loop clip, numbered screw
   markers and the part highlight drawn over it), step `03 / 05` in monospace, a short instruction,
   warnings inline, evidence chips (`0:12 · heard "step three"`, `verified by SAM`). Bottom bar:
   Back · **Done** · Next, swipe left/right, arrow keys. **Done** moves the step's screws into the
   screw tray at the bottom. In Put back mode the tray empties step by step; when it is empty:
   "Every screw is back."

## Copy
Short, concrete, sentence case. Verbs first ("Remove the 2 screws"). Numbers as digits.
Never raw states, ids or stack traces in the UI.

## Quality bar (check before saying done)
Screenshot every screen at 390×844 (and 1280 wide). No horizontal overflow, no orphan words in
pills, no native form controls showing, no element touching the screen edge, contrast AA, every
tap target ≥ 48 px, dark and light both correct.
