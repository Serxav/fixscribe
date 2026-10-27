# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the landing mosaic: fifteen objects FixScribe can analyze, each with one live step.

Run: ``python -m scripts.draw_mosaic`` -> writes web/templates/art/mosaic.html, a grid of inline
SVG tiles. The phone in the middle is the full analysis; around it, other categories each show
one part of the method (scan, point, number the screws, lift a part) or the safety gate refusing
a professional-only job. The animations are CSS classes (mz-*) styled in web/static/app.css; the
scroll choreography is in web/static/landing.js.
"""

from pathlib import Path

from scripts.draw_art import CORNERS, INK, LEG, LEG_H, MONO, TOP, WHITE, Iso, bolt, box

OUT = Path(__file__).resolve().parents[1] / "web" / "templates" / "art" / "mosaic.html"
S = 400  # every tile is a 400 x 400 drawing
ORANGE = "#ff5a1f"
YELLOW = "#ffd60a"
RED = "#e5202e"
STROKE = f'stroke="{INK}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"'


def tile(
    name: str,
    bg: str,
    body: str,
    label: str,
    chip: str,
    chip_dark: bool = False,
    delay: float = 0.0,
    floor: bool = False,
) -> str:
    """One square tile: the drawing in the top band, its label centred in the bottom band."""
    ink = INK if chip_dark else WHITE
    pill = "rgba(255,255,255,.55)" if chip_dark else "rgba(0,0,0,.28)"
    width = 26 + len(chip) * 8.4
    shadow = (
        '<ellipse cx="200" cy="338" rx="120" ry="9" fill="#000" opacity=".13"/>' if floor else ""
    )
    chip_svg = (
        f'<rect x="{200 - width / 2:.1f}" y="356" width="{width:.1f}" height="28" rx="14" fill="{pill}"/>'
        f'<text x="200" y="375" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{ink}">{chip}</text>'
    )
    return (
        f'<svg viewBox="0 0 {S} {S}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}" '
        f'style="--mz-delay:{delay:.2f}s"><rect width="{S}" height="{S}" fill="{bg}"/>'
        f'<g transform="translate(36 4) scale(.82)">{shadow}{body}</g>{chip_svg}</svg>'
    )


def gbox(x, y, w, h, tag="1") -> str:
    """Spark's grounding box: drawn in, held, redrawn (mz-box), with its number tag."""
    return (
        f'<rect class="mz-box" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{ORANGE}" stroke-width="4" pathLength="100"/>'
        f'<g class="mz-tag"><rect x="{x}" y="{y - 26}" width="24" height="24" fill="{ORANGE}"/>'
        f'<text x="{x + 12}" y="{y - 8}" text-anchor="middle" font-family="{MONO}" font-size="15" fill="{WHITE}">{tag}</text></g>'
    )


def ring(x, y, n, r=11) -> str:
    """A numbered fastener ring (mz-ring pulses in turn by --i)."""
    return (
        f'<g class="mz-ring" style="--i:{n}"><circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{YELLOW}" stroke-width="3.5"/>'
        f'<circle cx="{x + r}" cy="{y - r}" r="9" fill="{YELLOW}"/>'
        f'<text x="{x + r}" y="{y - r + 4.5}" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{INK}">{n}</text></g>'
    )


def scan() -> str:
    return (
        '<defs><linearGradient id="mzs" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        '<stop offset=".85" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity=".9"/></linearGradient></defs>'
        '<rect class="mz-scan" x="0" y="-90" width="400" height="90" fill="url(#mzs)"/>'
    )


def pro(x=20, y=20) -> str:
    return (
        f'<g class="mz-pro"><rect x="{x}" y="{y}" width="196" height="34" fill="{RED}"/>'
        f'<text x="{x + 12}" y="{y + 23}" font-family="{MONO}" font-size="14" fill="{WHITE}">PROFESSIONAL ONLY</text></g>'
    )


def screw(x, y, r=6) -> str:
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="#d9dde3" {STROKE.replace("3", "2", 1)}/><path d="M{x - r * 0.6} {y} h{r * 1.2}" stroke="{INK}" stroke-width="1.6"/>'


# --- the objects ------------------------------------------------------------------------------


def phone_parts(battery_class: str = "mz-lift") -> str:
    """The opened phone without overlays: frame, cameras, logic board, battery, speaker."""
    thin = f'stroke="{INK}" stroke-width="1.8" stroke-linejoin="round"'
    b = f'<rect x="113" y="16" width="174" height="330" rx="30" fill="#f4f6fb" stroke="{INK}" stroke-width="2.4"/>'
    b += "".join(
        f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{INK}"/>'
        for x, y, h in [(109, 80, 22), (109, 112, 36), (287, 104, 44)]
    )
    b += f'<rect x="124" y="27" width="152" height="308" rx="22" fill="#dfe4ee" {thin}/>'
    b += f'<rect x="134" y="38" width="56" height="56" rx="12" fill="#f4f6fb" {thin}/>'
    b += "".join(
        f'<circle cx="{x}" cy="{y}" r="10" fill="#1b2233" {thin}/><circle cx="{x - 3}" cy="{y - 3}" r="3" fill="#8fa3c8"/>'
        for x, y in [(150, 54), (174, 54), (150, 78)]
    )
    b += f'<circle cx="176" cy="79" r="4" fill="#ffe9a8" {thin}/>'
    b += f'<rect x="198" y="38" width="68" height="110" rx="6" fill="#2f3b52" {thin}/>'
    b += '<rect x="208" y="50" width="28" height="28" rx="2" fill="#1b2233" stroke="#7d8db0" stroke-width="1.2"/><rect x="242" y="52" width="16" height="12" fill="#1b2233"/><rect x="242" y="70" width="16" height="10" fill="#1b2233"/>'
    b += "".join(
        f'<rect x="{208 + i * 9}" y="88" width="6" height="4" fill="#c7a94a"/>' for i in range(6)
    )
    b += f'<rect x="208" y="122" width="26" height="10" rx="2" fill="#d9b54a" {thin}/>'
    b += '<path d="M221 132 V150 H246 V158" fill="none" stroke="#d9b54a" stroke-width="6"/>'
    b += f'<g class="{battery_class}"><rect x="136" y="158" width="128" height="138" rx="8" fill="#c7d1f6" stroke="{INK}" stroke-width="2"/>'
    b += f'<text x="150" y="190" font-family="{MONO}" font-size="11" fill="{INK}" opacity=".7">Li-ion 3.85 V</text>'
    b += f'<path d="M150 204 h96 M150 216 h70" stroke="{INK}" stroke-width="1.6" opacity=".35"/>'
    b += (
        "".join(
            f'<rect x="{x}" y="292" width="14" height="22" rx="3" fill="#222"/>' for x in (152, 234)
        )
        + "</g>"
    )
    b += f'<rect x="136" y="312" width="58" height="16" rx="4" fill="#f4f6fb" {thin}/>'
    b += "".join(
        f'<circle cx="{212 + i * 8}" cy="320" r="2" fill="{INK}" opacity=".6"/>' for i in range(7)
    )
    return b


SCREWS = [(206, 142), (258, 142), (144, 320), (186, 320)]


def phone() -> str:
    """The center tile: the phone with Spark's box, SAM's numbered screws and part labels."""
    b = phone_parts()
    for i, (x, y) in enumerate(SCREWS, start=1):
        b += (
            f'<circle cx="{x}" cy="{y}" r="4" fill="#d9dde3" stroke="{INK}" stroke-width="1.4"/>'
            + ring(x, y, i, r=8)
        )
    b += gbox(132, 154, 136, 146)
    labels = [
        ((266, 60), (300, 60), "logic board"),
        ((268, 228), (300, 228), "battery (Spark)"),
        ((134, 66), (102, 66), "cameras"),
        ((152, 304), (102, 304), "pull tabs"),
        ((190, 320), (300, 330), "screws 1–4 (SAM)"),
    ]
    lab = ""
    for (x1, y1), (x2, y2), name in labels:
        anchor = "start" if x2 > x1 else "end"
        tx = x2 + 4 if anchor == "start" else x2 - 4
        lab += f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{WHITE}" stroke-width="1"/><circle cx="{x1}" cy="{y1}" r="2" fill="{WHITE}"/>'
        lab += f'<text x="{tx}" y="{y2 + 3.5}" font-family="{MONO}" font-size="9.5" fill="{WHITE}" text-anchor="{anchor}">{name}</text>'
    b += f'<g class="mz-detail">{lab}</g>'
    b += scan()
    return b


def laptop() -> str:
    b = f'<rect x="60" y="96" width="280" height="196" rx="18" fill="{WHITE}" {STROKE}/>'
    b += "".join(
        f'<path d="M{150 + i * 14} 140 v60" stroke="{INK}" stroke-width="3" opacity=".35"/>'
        for i in range(8)
    )
    b += f'<rect x="110" y="230" width="180" height="38" rx="6" fill="#dfe3ee" {STROKE}/>'
    pts = [(84, 120), (200, 114), (316, 120), (84, 268), (316, 268), (200, 276)]
    for i, (x, y) in enumerate(pts, start=1):
        b += screw(x, y) + ring(x, y, i)
    return b


def chair() -> str:
    b = f'<rect x="150" y="52" width="110" height="128" rx="22" fill="{WHITE}" {STROKE}/>'
    b += f'<path d="M205 180 v10" {STROKE}/><rect x="120" y="186" width="170" height="30" rx="12" fill="{WHITE}" {STROKE}/>'
    b += f'<g class="mz-lift"><rect x="196" y="216" width="18" height="72" rx="4" fill="#ffd2c0" {STROKE}/></g>'
    b += f'<path d="M205 290 L105 318 M205 290 L305 318 M205 290 L160 330 M205 290 L250 330" {STROKE}/>'
    b += "".join(
        f'<circle cx="{x}" cy="{y}" r="9" fill="{WHITE}" {STROKE}/>'
        for x, y in [(105, 322), (305, 322), (160, 334), (250, 334)]
    )
    b += gbox(184, 210, 42, 84)
    return b


def bike() -> str:
    b = ""
    for cx in (110, 290):
        b += f'<circle cx="{cx}" cy="250" r="68" fill="none" stroke="{WHITE}" stroke-width="9"/><circle cx="{cx}" cy="250" r="68" fill="none" {STROKE}/>'
        b += "".join(
            f'<path d="M{cx} 250 l{60 * c:.1f} {60 * s:.1f}" stroke="{WHITE}" stroke-width="1.6" opacity=".7"/>'
            for c, s in [(1, 0), (0.5, 0.87), (-0.5, 0.87), (-1, 0), (-0.5, -0.87), (0.5, -0.87)]
        )
    b += f'<path d="M110 250 L180 170 L280 170 L200 250 Z M180 170 L168 140 M280 170 L290 250 M276 150 L300 128" stroke="{WHITE}" stroke-width="7" fill="none" stroke-linejoin="round" stroke-linecap="round"/>'
    b += f'<rect x="150" y="130" width="40" height="12" rx="6" fill="{WHITE}"/><circle cx="200" cy="250" r="18" fill="none" stroke="{WHITE}" stroke-width="5"/>'
    b += f'<path class="mz-chain" d="M200 232 L110 236 M200 268 L110 264" stroke="{YELLOW}" stroke-width="4" stroke-dasharray="6 6"/>'
    b += gbox(88, 214, 132, 70)
    return b


def washer() -> str:
    b = f'<rect x="92" y="44" width="216" height="296" rx="14" fill="{WHITE}" {STROKE}/>'
    b += f'<path d="M92 92 h216" {STROKE}/><rect x="112" y="60" width="70" height="18" rx="4" fill="#dfe3ee" {STROKE}/><circle cx="276" cy="69" r="10" fill="#dfe3ee" {STROKE}/>'
    b += f'<circle cx="200" cy="200" r="78" fill="#dfe3ee" {STROKE}/><circle class="mz-spin" cx="200" cy="200" r="56" fill="#c9d4e6" stroke="{INK}" stroke-width="3" stroke-dasharray="14 10"/>'
    b += f'<rect x="250" y="300" width="40" height="28" rx="5" fill="{WHITE}" {STROKE}/>'
    b += gbox(242, 292, 56, 44)
    return b


def faucet() -> str:
    b = f'<path d="M140 140 h90 a40 40 0 0 1 40 40 v34" fill="none" stroke="{WHITE}" stroke-width="26" stroke-linecap="round"/>'
    b += f'<path d="M140 140 h90 a40 40 0 0 1 40 40 v34" fill="none" stroke="{INK}" stroke-width="3" opacity=".0"/>'
    b += f'<rect x="120" y="120" width="44" height="170" rx="8" fill="{WHITE}" {STROKE}/><rect x="104" y="96" width="76" height="22" rx="10" fill="{WHITE}" {STROKE}/>'
    b += f'<rect x="88" y="290" width="108" height="20" rx="4" fill="{WHITE}" {STROKE}/>'
    b += '<g class="mz-drip"><path d="M270 226 q-8 14 0 18 q8 -4 0 -18 Z" fill="#7cc4ff"/></g>'
    b += f'<rect x="128" y="190" width="28" height="16" rx="3" fill="#7cc4ff" {STROKE}/>'
    b += gbox(118, 180, 48, 36)
    return b


def wheel() -> str:
    b = f'<circle cx="200" cy="190" r="140" fill="#2b2b2b" {STROKE}/><circle cx="200" cy="190" r="96" fill="#e9ecf1" {STROKE}/>'
    b += "".join(
        f'<path d="M200 190 l{80 * c:.1f} {80 * s:.1f}" stroke="#b8bfca" stroke-width="16" stroke-linecap="round"/>'
        for c, s in [(0, -1), (0.95, -0.31), (0.59, 0.81), (-0.59, 0.81), (-0.95, -0.31)]
    )
    b += f'<circle cx="200" cy="190" r="58" fill="{WHITE}" {STROKE}/>'
    nuts = [(200, 152), (236, 178), (222, 221), (178, 221), (164, 178)]
    order = [1, 3, 5, 2, 4]  # star pattern
    for (x, y), n in zip(nuts, order, strict=True):
        b += (
            f'<circle cx="{x}" cy="{y}" r="10" fill="#b8bfca" stroke="{INK}" stroke-width="2.5"/>'
            + ring(x, y, n, r=14)
        )
    return b


def panel() -> str:
    b = f'<rect x="96" y="70" width="208" height="262" rx="8" fill="{WHITE}" {STROKE}/>'
    for row in range(4):
        for col in range(6):
            b += f'<rect x="{114 + col * 30}" y="{98 + row * 56}" width="22" height="40" rx="3" fill="#dfe3ee" stroke="{INK}" stroke-width="2"/>'
            b += f'<rect x="{120 + col * 30}" y="{106 + row * 56 + (0 if (row + col) % 3 else 14)}" width="10" height="12" fill="{INK}"/>'
    b += '<defs><pattern id="mzh" width="28" height="28" patternTransform="rotate(45)" patternUnits="userSpaceOnUse"><rect width="14" height="28" fill="#ffd60a"/><rect x="14" width="14" height="28" fill="#161616"/></pattern></defs>'
    b += '<rect x="0" y="336" width="400" height="10" fill="url(#mzh)"/>'
    b += pro()
    return b


def drill() -> str:
    b = f'<path d="M96 120 h170 a26 26 0 0 1 26 26 v28 a26 26 0 0 1 -26 26 h-112 z" fill="{WHITE}" {STROKE}/>'
    b += f'<path d="M160 200 l-18 96 h60 l10 -96" fill="{WHITE}" {STROKE}/><rect x="126" y="292" width="98" height="40" rx="8" fill="#b9a786" {STROKE}/>'
    b += f'<g class="mz-lift"><rect x="292" y="140" width="34" height="40" rx="6" fill="#dfe3ee" {STROKE}/><path d="M326 160 h44" stroke="{INK}" stroke-width="5" stroke-linecap="round"/></g>'
    b += gbox(286, 130, 92, 60)
    return b


def coffee() -> str:
    b = f'<rect x="100" y="56" width="200" height="270" rx="14" fill="{WHITE}" {STROKE}/>'
    b += f'<rect x="246" y="40" width="44" height="120" rx="6" fill="#cfe8ff" {STROKE}/><rect class="mz-level" x="252" y="88" width="32" height="66" fill="#7cc4ff"/>'
    b += f'<rect x="140" y="150" width="120" height="22" rx="6" fill="#dfe3ee" {STROKE}/><path d="M260 161 h40" {STROKE}/>'
    b += f'<path d="M168 230 h64 l-8 56 h-48 z" fill="{WHITE}" {STROKE}/><path d="M232 244 a14 14 0 0 1 0 28" fill="none" {STROKE}/>'
    b += f'<path d="M100 300 h200" {STROKE}/>'
    b += ring(268, 100, 1, r=12)
    return b


def controller() -> str:
    b = f'<path d="M110 150 q90 -36 180 0 q40 16 46 90 q4 60 -38 62 q-26 0 -46 -40 h-104 q-20 40 -46 40 q-42 -2 -38 -62 q6 -74 46 -90 z" fill="{WHITE}" {STROKE}/>'
    b += f'<circle cx="160" cy="214" r="20" fill="#dcd6ff" {STROKE}/><circle class="mz-drift" cx="160" cy="214" r="8" fill="{INK}"/>'
    b += f'<circle cx="240" cy="250" r="20" fill="#dcd6ff" {STROKE}/><circle cx="240" cy="250" r="8" fill="{INK}"/>'
    b += "".join(
        f'<circle cx="{x}" cy="{y}" r="8" fill="#dcd6ff" stroke="{INK}" stroke-width="2"/>'
        for x, y in [(276, 196), (296, 214), (276, 232), (256, 214)]
    )
    b += gbox(132, 186, 56, 56)
    return b


def shelf() -> str:
    b = f'<rect x="110" y="40" width="180" height="300" fill="{WHITE}" {STROKE}/>'
    for i, y in enumerate((110, 180, 250), start=1):
        b += f'<g class="mz-slide" style="--i:{i}"><rect x="116" y="{y}" width="168" height="10" fill="#c9d4c8" {STROKE}/></g>'
    for i, (x, y) in enumerate([(124, 115), (276, 115), (124, 185), (276, 185)], start=1):
        b += (
            f'<circle cx="{x}" cy="{y}" r="6" fill="#d9dde3" stroke="{INK}" stroke-width="2"/>'
            + ring(x, y, i, r=9)
        )
    return b


def lamp() -> str:
    b = f'<path d="M140 320 h120" {STROKE}/><rect x="150" y="310" width="100" height="16" rx="6" fill="{WHITE}" {STROKE}/>'
    b += f'<path d="M200 310 L150 200 L250 120" fill="none" stroke="{INK}" stroke-width="8" stroke-linecap="round"/><circle cx="150" cy="200" r="9" fill="{WHITE}" {STROKE}/>'
    b += f'<path d="M232 96 l70 30 l-30 54 l-60 -40 z" fill="{WHITE}" {STROKE}/>'
    b += f'<g class="mz-glow"><circle cx="272" cy="160" r="16" fill="#fff4c2" stroke="{INK}" stroke-width="2.5"/></g>'
    b += gbox(250, 138, 46, 46)
    return b


def boiler() -> str:
    b = f'<rect x="110" y="64" width="180" height="240" rx="12" fill="{WHITE}" {STROKE}/>'
    b += f'<rect x="140" y="96" width="120" height="44" rx="6" fill="#2b2b2b" {STROKE}/><text x="200" y="125" text-anchor="middle" font-family="{MONO}" font-size="18" fill="#7ee2a0">1.4 bar</text>'
    b += "".join(
        f'<path d="M{x} 304 v52" stroke="{WHITE}" stroke-width="12"/><path d="M{x} 304 v52" stroke="{INK}" stroke-width="2" opacity=".0"/>'
        for x in (150, 180, 220, 250)
    )
    b += f'<path d="M150 304 v40 M180 304 v40 M220 304 v40 M250 304 v40" stroke="{INK}" stroke-width="12" opacity=".2"/>'
    b += pro(102, 160)
    return b


def engine() -> str:
    b = f'<rect x="78" y="70" width="244" height="232" rx="16" fill="#8e97a6" {STROKE}/>'
    b += f'<rect x="102" y="96" width="196" height="104" rx="22" fill="#c9ced6" {STROKE}/>'
    b += "".join(
        f'<path d="M{x} 104 v88" stroke="{INK}" stroke-width="2" opacity=".25"/>'
        for x in (122, 278)
    )
    for x, n in zip((140, 180, 220, 260), (1, 3, 4, 2), strict=True):
        b += (
            f'<circle cx="{x}" cy="148" r="13" fill="#2b2b2b" {STROKE}/><circle cx="{x}" cy="148" r="5" fill="#b8bfca"/>'
            + ring(x, 148, n, r=17)
        )
    b += f'<circle cx="132" cy="246" r="18" fill="{YELLOW}" {STROKE}/><path d="M124 246 h16" stroke="{INK}" stroke-width="3"/>'
    b += f'<path d="M262 220 q30 0 30 30 t-30 30" fill="none" stroke="{YELLOW}" stroke-width="6" stroke-linecap="round"/>'
    b += '<path d="M178 300 q0 40 60 40" fill="none" stroke="#2b2b2b" stroke-width="12" stroke-linecap="round"/>'
    b += gbox(108, 222, 48, 48, "2")
    return b


def pc() -> str:
    b = f'<rect x="84" y="30" width="232" height="306" rx="10" fill="#2b3040" {STROKE}/>'
    b += f'<rect x="104" y="50" width="170" height="196" rx="4" fill="#2f6b52" {STROKE}/>'
    b += f'<rect x="120" y="66" width="62" height="62" rx="6" fill="#20242c" {STROKE}/><g class="mz-spin"><path d="M151 70 v54 M124 97 h54 M132 78 l38 38 M170 78 l-38 38" stroke="#7d8db0" stroke-width="5" stroke-linecap="round"/></g>'
    b += "".join(
        f'<rect x="{200 + i * 14}" y="64" width="8" height="70" rx="2" fill="#c9d4e6" {STROKE.replace("3", "1.6", 1)}/>'
        for i in range(4)
    )
    b += f'<g class="mz-lift"><rect x="104" y="178" width="196" height="44" rx="6" fill="#16191f" {STROKE}/>'
    b += (
        "".join(
            f'<circle cx="{x}" cy="200" r="15" fill="#3a3f4f" stroke="#7d8db0" stroke-width="2"/>'
            for x in (142, 186, 230)
        )
        + "</g>"
    )
    b += f'<rect x="104" y="268" width="196" height="50" rx="4" fill="#3a3f4f" {STROKE}/>'
    b += gbox(98, 172, 208, 56)
    return b


def drone() -> str:
    b = ""
    for x, y in [(104, 104), (296, 104), (104, 266), (296, 266)]:
        b += f'<path d="M200 185 L{x} {y}" stroke="{WHITE}" stroke-width="10" stroke-linecap="round"/>'
        b += f'<circle cx="{x}" cy="{y}" r="46" fill="none" stroke="{WHITE}" stroke-width="2" opacity=".5"/>'
        b += f'<g class="mz-spin"><path d="M{x - 40} {y} h80" stroke="{WHITE}" stroke-width="6" stroke-linecap="round"/></g><circle cx="{x}" cy="{y}" r="9" fill="{WHITE}" {STROKE}/>'
    b += f'<rect x="166" y="150" width="68" height="72" rx="16" fill="{WHITE}" {STROKE}/><circle cx="200" cy="232" r="10" fill="#1b2233" {STROKE}/>'
    for i, (x, y) in enumerate([(150, 144), (250, 144), (150, 226), (250, 226)], start=1):
        b += (
            f'<circle cx="{x}" cy="{y}" r="4" fill="#d9dde3" stroke="{INK}" stroke-width="1.4"/>'
            + ring(x, y, i, r=9)
        )
    return b


def aircon() -> str:
    b = f'<rect x="56" y="96" width="288" height="112" rx="20" fill="{WHITE}" {STROKE}/>'
    b += "".join(
        f'<path d="M84 {178 + i * 9} h232" stroke="{INK}" stroke-width="2" opacity=".35"/>'
        for i in range(3)
    )
    b += f'<rect x="278" y="118" width="40" height="20" rx="4" fill="#20242c"/><text x="298" y="133" text-anchor="middle" font-family="{MONO}" font-size="12" fill="#7ee2a0">22°</text>'
    b += '<path d="M318 208 v50 q0 20 -20 20 h-60" fill="none" stroke="#b8bfca" stroke-width="10"/><path d="M300 208 v40 q0 14 -14 14 h-48" fill="none" stroke="#7cc4ff" stroke-width="7"/>'
    b += f'<text x="236" y="306" font-family="{MONO}" font-size="12" fill="{WHITE}" text-anchor="end">R32 refrigerant line</text>'
    b += pro(56, 40)
    return b


def guitar() -> str:
    b = f'<path d="M176 30 h48 l14 150 h-76 z" fill="#f2e3c9" {STROKE}/><rect x="182" y="180" width="36" height="170" fill="#5a3a22" {STROKE}/>'
    b += "".join(
        f'<path d="M{186 + i * 5.6:.1f} 60 V350" stroke="#e9ecf1" stroke-width="1.4"/>'
        for i in range(6)
    )
    pegs = [(152, 66), (148, 106), (144, 146), (248, 66), (252, 106), (256, 146)]
    for i, (x, y) in enumerate(pegs, start=1):
        b += (
            f'<rect x="{x - 14}" y="{y - 8}" width="28" height="16" rx="8" fill="#d9dde3" {STROKE.replace("3", "2", 1)}/>'
            + ring(x, y, i, r=10)
        )
    b += "".join(
        f'<path d="M182 {220 + i * 34} h36" stroke="#c9ced6" stroke-width="2.5"/>' for i in range(4)
    )
    return b


def lock() -> str:
    b = f'<rect x="60" y="20" width="110" height="360" fill="#c9a77a" {STROKE}/><rect x="170" y="20" width="12" height="360" fill="#a4865f" {STROKE}/>'
    b += f'<rect x="196" y="56" width="66" height="290" rx="10" fill="{WHITE}" {STROKE}/>'
    b += f'<rect x="212" y="120" width="34" height="18" rx="4" fill="#b8bfca" {STROKE}/>'
    b += f'<circle cx="229" cy="232" r="22" fill="#e9c46a" {STROKE}/><path d="M229 222 v20 M223 222 h12" stroke="{INK}" stroke-width="3.5" stroke-linecap="round"/>'
    for i, y in enumerate((80, 322), start=1):
        b += (
            f'<circle cx="229" cy="{y}" r="6" fill="#d9dde3" stroke="{INK}" stroke-width="2"/>'
            + ring(229, y, i, r=10)
        )
    b += gbox(200, 202, 58, 60)
    return b


def table_tile() -> str:
    iso = Iso(200, 196, 1.85)
    tones = ("#ffffff", "#e4e9fb", "#c7d1f6")
    b = "".join(box(iso, x, y, 0, LEG, LEG, LEG_H, tones) for x, y in CORNERS)
    b += "".join(bolt(iso, x + LEG / 2, y + LEG / 2, LEG_H + 4, LEG_H + 14) for x, y in CORNERS)
    b += f'<g class="mz-lift">{box(iso, 0, 0, LEG_H + 30, *TOP, tones)}</g>'
    return b


# Grid order: 7 columns x 3 rows on desktop (3 x 7 on a phone); the phone (index 10) is the center.
TILES = [
    (
        "Laptop",
        "#1b2a55",
        laptop,
        "Laptop underside with six numbered screws",
        "laptop · 6 screws",
        False,
    ),
    (
        "Office chair",
        ORANGE,
        chair,
        "Office chair with its gas lift pointed at",
        "chair · gas lift",
        False,
    ),
    ("Bicycle", "#0f5132", bike, "Bicycle with the chain pointed at", "bike · chain", False),
    (
        "Car engine",
        "#20242c",
        engine,
        "Car engine with spark plugs numbered in firing order and the oil cap pointed at",
        "engine · spark plugs",
        False,
    ),
    (
        "Washing machine",
        "#e8e2d4",
        washer,
        "Washing machine with the drain filter pointed at",
        "washer · filter",
        True,
    ),
    (
        "Electrical panel",
        "#1d1d1f",
        panel,
        "Electrical panel: professional only, no steps given",
        "mains panel · refused",
        False,
    ),
    (
        "Drone",
        "#0e3a5c",
        drone,
        "Drone with the four motor screws numbered",
        "drone · motors",
        False,
    ),
    (
        "Faucet",
        "#121212",
        faucet,
        "Leaking faucet with the cartridge pointed at",
        "faucet · leak",
        False,
    ),
    (
        "Car wheel",
        "#f3f2ee",
        wheel,
        "Car wheel with the lug nuts numbered in star order",
        "wheel · star order",
        True,
    ),
    (
        "Desktop computer",
        "#d7dde8",
        pc,
        "Desktop computer with the graphics card pointed at",
        "PC · graphics card",
        True,
    ),
    (
        "Smartphone",
        "#0866ff",
        phone,
        "Phone battery swap: battery pointed at, four screws numbered, battery lifted out",
        "phone · battery swap",
        False,
    ),
    ("Drill", "#c9b99c", drill, "Drill with the chuck pointed at", "drill · chuck", True),
    (
        "Coffee machine",
        "#6b4f3a",
        coffee,
        "Coffee machine with the water tank numbered",
        "coffee · descale",
        False,
    ),
    (
        "Guitar",
        "#7a2e1d",
        guitar,
        "Guitar headstock with six tuning pegs numbered",
        "guitar · restring",
        False,
    ),
    (
        "Game controller",
        "#8e7dff",
        controller,
        "Game controller with the drifting stick pointed at",
        "controller · drift",
        False,
    ),
    ("Bookshelf", "#dbe9e1", shelf, "Bookshelf with cam locks numbered", "shelf · cam locks", True),
    ("Desk lamp", "#ffb340", lamp, "Desk lamp with the socket pointed at", "lamp · socket", True),
    (
        "Air conditioner",
        "#5b6b7a",
        aircon,
        "Air conditioner refrigerant line: professional only, no steps given",
        "AC gas · refused",
        False,
    ),
    (
        "Gas boiler",
        "#3a3a3a",
        boiler,
        "Gas boiler: professional only, no steps given",
        "gas boiler · refused",
        False,
    ),
    (
        "Door lock",
        "#e9d7b8",
        lock,
        "Door lock with the cylinder pointed at and two screws numbered",
        "lock · cylinder",
        True,
    ),
    (
        "Side table",
        "#a9c1ff",
        table_tile,
        "Side table with its top lifting off",
        "table · assemble",
        True,
    ),
]
CENTER = 10
STANDING = {
    "Office chair",
    "Washing machine",
    "Drill",
    "Coffee machine",
    "Desk lamp",
    "Gas boiler",
    "Side table",
}


def mosaic() -> str:
    figures = []
    for i, (name, bg, draw, label, chip, dark) in enumerate(TILES):
        center = ' data-center="1"' if i == CENTER else ""
        svg = tile(
            name, bg, draw(), label, chip, dark, delay=-(i * 0.37) % 3, floor=name in STANDING
        )
        figures.append(f'<figure class="mz-tile"{center}>{svg}</figure>')
    return '<div class="mz-grid" data-mosaic>\n' + "\n".join(figures) + "\n</div>\n"


def main() -> int:
    OUT.write_text(mosaic(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
