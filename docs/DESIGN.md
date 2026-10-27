# FixScribe design v5 — "Civic editorial, warmer"

References: the 2025-26 sites of the US National Design Studio (grid, restraint) and the page
organization of anthropic.com (two-tone statements, cards with rows, tag + picture tiles, dark
footer, calm reveal on scroll). We borrow structure, never brand: no logos, fonts or signature
colors of either. FixScribe must look like a serious public tool, not like an AI demo.

## v5 additions
- Header: section pills left, wordmark centered (the three-step glyph), one dark pill right.
- Big statements are two-tone: first sentence Inter Tight 500 in ink, the rest Instrument Serif
  in grey (`.headline .lead` / `.rest`).
- Soft cards (`.card-x`, radius 14 px) for things you can act on; hairlines for lists.
- Illustrations are drawn by `scripts/draw_art.py` (isometric, manual style, one color field each).
- Motion: `[data-reveal]` rises in once; the hero table comes apart on scroll (`[data-assemble]`);
  the agent trace appears line by line. All of it off with reduced motion, visible without JS.
- Radius: 14 px cards and media, 10 px buttons, pills 999 px. (Overrides rule 7 below.)

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
