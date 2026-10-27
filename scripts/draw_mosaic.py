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
) -> str:
    color = INK if chip_dark else WHITE
    chip_svg = (
        f'<rect x="20" y="352" width="{14 + len(chip) * 9.0:.0f}" height="30" rx="15" fill="none" stroke="{color}" stroke-opacity=".55"/>'
        f'<text x="34" y="372" font-family="{MONO}" font-size="14" fill="{color}">{chip}</text>'
    )
    return (
        f'<svg viewBox="0 0 {S} {S}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}" '
        f'style="--mz-delay:{delay:.2f}s"><rect width="{S}" height="{S}" fill="{bg}"/>{body}{chip_svg}</svg>'
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


def phone() -> str:
    b = f'<rect x="118" y="44" width="164" height="300" rx="26" fill="{WHITE}" {STROKE}/>'
    b += f'<rect x="132" y="58" width="136" height="272" rx="16" fill="#e9edf5" {STROKE}/>'
    b += f'<rect x="146" y="70" width="44" height="44" rx="10" fill="{WHITE}" {STROKE}/><circle cx="168" cy="92" r="11" fill="#c9d0e2" {STROKE}/>'
    b += f'<g class="mz-lift"><rect x="150" y="128" width="100" height="150" rx="8" fill="#c7d1f6" {STROKE}/>'
    b += f'<path d="M168 150 h64 M168 166 h64 M168 182 h40" stroke="{INK}" stroke-width="2.5" opacity=".5"/>'
    b += f'<rect x="232" y="286" width="22" height="12" rx="2" fill="{WHITE}" {STROKE}/></g>'
    for i, (x, y) in enumerate([(150, 308), (250, 308), (214, 94), (250, 94)], start=1):
        b += screw(x, y) + ring(x, y, i)
    b += gbox(144, 122, 112, 162)
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


def table_tile() -> str:
    iso = Iso(200, 196, 1.85)
    tones = ("#ffffff", "#e4e9fb", "#c7d1f6")
    b = "".join(box(iso, x, y, 0, LEG, LEG, LEG_H, tones) for x, y in CORNERS)
    b += "".join(bolt(iso, x + LEG / 2, y + LEG / 2, LEG_H + 4, LEG_H + 14) for x, y in CORNERS)
    b += f'<g class="mz-lift">{box(iso, 0, 0, LEG_H + 30, *TOP, tones)}</g>'
    return b


# Grid order: 5 columns x 3 rows on desktop; the phone (index 7) is the center tile.
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
        "Smartphone",
        "#3760f2",
        phone,
        "Phone repair: battery pointed at, four screws numbered, the battery lifted out",
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
        "Gas boiler",
        "#3a3a3a",
        boiler,
        "Gas boiler: professional only, no steps given",
        "gas boiler · refused",
        False,
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
CENTER = 7


def mosaic() -> str:
    figures = []
    for i, (name, bg, draw, label, chip, dark) in enumerate(TILES):
        center = ' data-center="1"' if i == CENTER else ""
        svg = tile(name, bg, draw(), label, chip, dark, delay=-(i * 0.37) % 3)
        figures.append(f'<figure class="mz-tile"{center}>{svg}</figure>')
    return '<div class="mz-grid" data-mosaic>\n' + "\n".join(figures) + "\n</div>\n"


def main() -> int:
    OUT.write_text(mosaic(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
