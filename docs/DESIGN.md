# FixScribe design v4 — "Civic editorial"

Reference: the 2025-26 sites of the US National Design Studio (ndstudio.gov, trumprx.gov).
FixScribe must look like a serious public tool, not like an AI demo: plain words, one typeface,
a strict grid, lots of space, and the real media doing the talking.

## Rules (check every page against them)
1. **One family, regular weight.** Inter Tight 400 everywhere; 500 only for small headings
   (`.h3`). Hierarchy comes from size and space, never from bold. Tracking `-0.02em`.
2. **Mono for data.** JetBrains Mono for times, counts, ids, model names, tool calls (`.mono`, `.chip`).
3. **12-column grid.** `.grid12`; labels in the left half (`.col-l`, columns 1-5), content in the
   right half (`.col-r`, 7-12; `.col-r-wide` 7-12 wider). Outer margin 20 px phone / 32 px desktop.
   On a phone everything is one column.
4. **Hairlines, not boxes.** Sections start with `.sect` (roman numeral + name on a 1 px rule).
   Lists are rows on rules (`.rows`). Use `.glass` (a flat paper block, no radius, no shadow) only
   when a block must stand apart (a form, a code trace).
5. **Square media.** Images and video have no radius and sit on `--media` (#0e0e0e). Full-bleed
   media uses `.bleed`.
6. **Color is rare.** Ink `#010101` on surface `#f2f2f2`. Accent `#3760f2` only for links and the
   one thing that needs attention. Status: ok `#1d7a3a`, warn `#a35a00`, bad `#bf000f`.
7. **Buttons are rectangles.** Primary = black block (`.btn-primary`), secondary = hairline
   (`.btn-glass`), tertiary = text with an arrow (`.btn-text.arrow`). Radius 2 px max.
8. **No decoration.** No gradients, glows, blobs, emoji, glass blur on content, rounded pills,
   drop shadows or icons that only decorate. A line icon is allowed only when it carries meaning.
9. **Copy:** short, literal, honest. Never claim a feature that does not run today.
10. **Motion:** opacity and small translate only, 200-350 ms, and none with reduced motion.

## Tokens (web/static/app.css)
`--surface #f2f2f2`, `--paper #fafafa`, `--ink #010101`, `--ink-2 #3a3a3a`, `--ink-3 #6b6b6b`,
`--rule rgba(0,0,0,.14)`, `--accent #3760f2`, `--media #0e0e0e`, `--font`, `--mono`,
`--margin`, `--gutter`. Older names (`--glass`, `--hair`, `--r-*`) are kept as aliases.

## Type scale
`.display` 34-60 px · `.title` 28-44 px · `.prose` 20-26 px · `.h2` 26 px · `.h3` 19 px ·
body 17 px · `.small` 14 px · `.mono` 0.86 em.

## Full-screen pages
Film, live coach and repair mode are dark, full screen, media first. Same rules: one family,
mono for data, square corners, white text, no glows.
