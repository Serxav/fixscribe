# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the landing illustrations as SVG (isometric, furniture-manual style).

Run: ``python -m scripts.draw_art`` -> writes web/templates/art/*.svg (inlined by the templates,
so they use the page fonts). Every drawing shows one real step of FixScribe's method, using
one example object: a small side table made of a top (A), four legs (B) and four hanger bolts (C).
No external images, no AI-generated pictures: geometry only.
"""

import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "templates" / "art"

INK = "#0b1020"
WHITE = "#ffffff"
FONT = "Inter Tight, Helvetica, Arial, sans-serif"
MONO = "JetBrains Mono, ui-monospace, Menlo, monospace"
COS = math.cos(math.radians(30))


class Iso:
    """Isometric projection: x goes down-right, y down-left, z up."""

    def __init__(self, ox: float, oy: float, k: float) -> None:
        self.ox, self.oy, self.k = ox, oy, k

    def p(self, x: float, y: float, z: float) -> tuple[float, float]:
        return (self.ox + (x - y) * COS * self.k, self.oy + (x + y) * 0.5 * self.k - z * self.k)

    def pts(self, *points: tuple[float, float, float]) -> str:
        return " ".join(f"{a:.1f},{b:.1f}" for a, b in (self.p(*q) for q in points))


def box(
    iso: Iso, x0, y0, z0, dx, dy, dz, tones=("#ffffff", "#e3e7f1", "#c9d0e2"), stroke=INK, sw=1.6
) -> str:
    """A cuboid: top, right (+x) and left (+y) faces."""
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    top = iso.pts((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
    right = iso.pts((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))
    left = iso.pts((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1))
    style = f'stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"'
    return (
        f'<polygon points="{right}" fill="{tones[1]}" {style}/>'
        f'<polygon points="{left}" fill="{tones[2]}" {style}/>'
        f'<polygon points="{top}" fill="{tones[0]}" {style}/>'
    )


def ellipse(iso: Iso, x, y, z, r, fill, stroke=INK, sw=1.4) -> str:
    cx, cy = iso.p(x, y, z)
    rx, ry = r * iso.k * 1.22, r * iso.k * 0.71
    return f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def bolt(iso: Iso, x, y, z0, z1, color=INK) -> str:
    """A hanger bolt standing up: shaft from z0 to z1, threads as ticks."""
    a, b = iso.p(x, y, z0), iso.p(x, y, z1)
    out = f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{color}" stroke-width="{0.9 * iso.k:.1f}" stroke-linecap="round"/>'
    for i in range(1, 5):
        z = z0 + (z1 - z0) * (0.45 + i * 0.11)
        cx, cy = iso.p(x, y, z)
        out += f'<line x1="{cx - 0.8 * iso.k:.1f}" y1="{cy + 0.3 * iso.k:.1f}" x2="{cx + 0.8 * iso.k:.1f}" y2="{cy - 0.3 * iso.k:.1f}" stroke="{WHITE}" stroke-width="1"/>'
    return out


def dashed(iso: Iso, a3, b3, color=INK, sw=1.4) -> str:
    a, b = iso.p(*a3), iso.p(*b3)
    return f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{color}" stroke-width="{sw}" stroke-dasharray="5 5"/>'


def letter(cx, cy, text, r=17, fill=WHITE, ink=INK) -> str:
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" stroke="{ink}" stroke-width="1.6"/>'
        f'<text x="{cx:.1f}" y="{cy + 5.5:.1f}" text-anchor="middle" font-family="{MONO}" font-size="16" fill="{ink}">{text}</text>'
    )


def text(x, y, s, size=18, fill=INK, mono=False, anchor="start", weight=400, opacity=1.0) -> str:
    family = MONO if mono else FONT
    spacing = "0" if mono else "-0.02em"
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
        f'font-weight="{weight}" letter-spacing="{spacing}" opacity="{opacity}">{s}</text>'
    )


def svg(w, h, body, label, bg=None) -> str:
    back = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}" '
        f'preserveAspectRatio="xMidYMid slice">{back}{body}</svg>\n'
    )


# --- the table ------------------------------------------------------------------------------

TOP = (80, 80, 6)
LEG = 7
LEG_H = 48
CORNERS = [(5, 5), (68, 5), (5, 68), (68, 68)]


def table(
    iso: Iso, lift: float = 0.0, tones=None, bolts_up: float = 0.0, guides=False, stroke=INK
) -> str:
    """The side table. ``lift`` raises the top (exploded view); ``bolts_up`` floats the bolts."""
    tones = tones or ("#ffffff", "#e3e7f1", "#c9d0e2")
    out = ""
    for x, y in CORNERS:  # back to front
        out += box(iso, x, y, 0, LEG, LEG, LEG_H, tones, stroke)
        cx, cy = x + LEG / 2, y + LEG / 2
        z0 = LEG_H + bolts_up
        out += bolt(iso, cx, cy, z0 - 2, z0 + 10, stroke)
        if guides:
            out += dashed(iso, (cx, cy, z0 + 10), (cx, cy, LEG_H + lift), stroke)
    out += box(iso, 0, 0, LEG_H + lift, *TOP, tones, stroke)
    return out


def grid(w, h, step, color, opacity) -> str:
    lines = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}"/>' for x in range(step, w, step))
    lines += "".join(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}"/>' for y in range(step, h, step))
    return f'<g stroke="{color}" stroke-width="1" opacity="{opacity}">{lines}</g>'


# --- drawings ---------------------------------------------------------------------------------


def hero() -> str:
    w, h = 1600, 900
    iso = Iso(520, 540, 4.3)
    blue_tones = ("#ffffff", "#e4e9fb", "#c7d1f6")
    body = grid(w, h, 40, WHITE, 0.08)
    body += table(iso, lift=40, tones=blue_tones, bolts_up=10, guides=True)
    # arrow: the top comes down
    ax, ay = iso.p(0, 0, LEG_H + 40 + TOP[2])
    body += f'<path d="M{ax:.0f} {ay - 80:.0f} V{ay - 16:.0f} m-9 -14 l9 14 l9 -14" fill="none" stroke="{WHITE}" stroke-width="2"/>'
    # callouts: letter at the part, leader to a label on the right
    parts = [
        ((60, 20, LEG_H + 46), "A", "Tabletop", "proven at 00:12.4 · SAM fill 81%"),
        (
            (71.5, 8.5, LEG_H + 18),
            "B",
            "Hanger bolt ×4",
            "said at 00:44.2: “the bolt goes into the leg”",
        ),
        ((71.5, 8.5, 22), "C", "Leg ×4", "proven at 00:31.0 · SAM fill 77%"),
    ]
    for i, (where, mark, name, proof) in enumerate(parts):
        px, py = iso.p(*where)
        lx, ly = 980, 300 + i * 150
        body += f'<polyline points="{px:.0f},{py:.0f} {lx - 60},{ly - 6} {lx - 24},{ly - 6}" fill="none" stroke="{WHITE}" stroke-width="1.4"/>'
        body += f'<circle cx="{px:.0f}" cy="{py:.0f}" r="4" fill="{WHITE}"/>'
        body += letter(lx, ly - 6, mark, fill="#3760f2", ink=WHITE)
        body += text(lx + 32, ly, name, 30, WHITE)
        body += text(lx + 32, ly + 32, proof, 16, WHITE, mono=True, opacity=0.8)
    body += text(
        48,
        h - 44,
        "Exploded view, drawn only from parts the agent proved on the video.",
        16,
        WHITE,
        mono=True,
        opacity=0.8,
    )
    return svg(
        w,
        h,
        body,
        "Exploded view of a side table with three proven parts: tabletop, legs and hanger bolts",
        "#3760f2",
    )


def tile_identify() -> str:
    w, h = 800, 1000
    iso = Iso(400, 520, 3.5)
    body = table(iso, tones=("#ffffff", "#dfe3ee", "#c3cadb"))
    # viewfinder corners
    for cx, cy, dx, dy in (
        (150, 200, 1, 1),
        (650, 200, -1, 1),
        (150, 760, 1, -1),
        (650, 760, -1, -1),
    ):
        body += f'<path d="M{cx} {cy + 40 * dy} V{cy} H{cx + 40 * dx}" fill="none" stroke="{WHITE}" stroke-width="3"/>'
    chips = [
        ("object", "side table"),
        ("category", "furniture"),
        ("task", "assemble"),
        ("hazard", "heavy part"),
    ]
    y = 840
    x = 80
    for key, value in chips:
        label = f"{key}: {value}"
        width = 14 + len(label) * 10.2
        if x + width > w - 60:
            x, y = 80, y + 52
        body += f'<rect x="{x}" y="{y}" width="{width:.0f}" height="36" fill="none" stroke="{WHITE}" stroke-opacity=".7"/>'
        body += text(x + 10, y + 24, label, 17, WHITE, mono=True)
        x += width + 12
    return svg(
        w,
        h,
        body,
        "The object is identified: side table, furniture, assemble, heavy part",
        "#1b2a55",
    )


def tile_listen() -> str:
    w, h = 800, 1000
    body = ""
    heights = [abs(math.sin(i * 0.61) * math.cos(i * 0.23)) for i in range(64)]
    for i, v in enumerate(heights):
        x = 70 + i * 10.4
        bar = 12 + v * 170
        hot = 22 <= i <= 37
        color = "#ffd60a" if hot else WHITE
        body += f'<rect x="{x:.1f}" y="{330 - bar / 2:.1f}" width="5" height="{bar:.1f}" fill="{color}" opacity="{1 if hot else 0.55}"/>'
    body += f'<line x1="70" y1="470" x2="730" y2="470" stroke="{WHITE}" stroke-opacity=".25"/>'
    lines = [
        ("00:41.0", "Take one bolt from the bag,", False),
        ("00:44.2", "the bolt goes into the leg", True),
        ("00:47.9", "and turn it by hand until it stops.", False),
    ]
    for i, (t, words, hot) in enumerate(lines):
        y = 560 + i * 92
        body += text(70, y, t, 18, WHITE, mono=True, opacity=0.6)
        if hot:
            body += f'<rect x="196" y="{y - 30}" width="{len(words) * 14.6:.0f}" height="42" fill="#ffd60a"/>'
        body += text(206, y, words, 27, INK if hot else WHITE)
    body += text(70, 900, "quote found in the narration", 18, "#ffd60a", mono=True)
    return svg(
        w,
        h,
        body,
        "The narration is transcribed and timed; the quote for a step is found in it",
        "#121212",
    )


def tile_point() -> str:
    w, h = 800, 1000
    fx, fy, fw, fh = 70, 150, 660, 600  # the video frame
    body = f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" fill="#2b2b2b"/>'
    # top view of the parts on the floor
    body += f'<rect x="{fx + 60}" y="{fy + 50}" width="300" height="300" fill="#d8cbb4" stroke="#1a1a1a" stroke-width="2"/>'
    for i in range(4):
        body += f'<rect x="{fx + 410}" y="{fy + 60 + i * 52}" width="190" height="30" fill="#c9b99c" stroke="#1a1a1a" stroke-width="2"/>'
    bolts = [
        (fx + 120, fy + 450, 120),
        (fx + 200, fy + 470, 120),
        (fx + 390, fy + 455, 64),
        (fx + 470, fy + 480, 64),
    ]
    for x, y, length in bolts:
        body += f'<line x1="{x}" y1="{y}" x2="{x + length}" y2="{y}" stroke="#d9dde3" stroke-width="9" stroke-linecap="round"/>'
        body += f'<circle cx="{x}" cy="{y}" r="9" fill="#eef0f3"/>'
    # 0..1000 ticks along the frame
    for i in range(11):
        tx = fx + fw * i / 10
        ty = fy + fh * i / 10
        body += f'<line x1="{tx:.0f}" y1="{fy - 10}" x2="{tx:.0f}" y2="{fy}" stroke="{INK}" stroke-width="1.4"/>'
        body += f'<line x1="{fx - 10}" y1="{ty:.0f}" x2="{fx}" y2="{ty:.0f}" stroke="{INK}" stroke-width="1.4"/>'
    body += text(fx, fy - 20, "0", 15, INK, mono=True)
    body += text(fx + fw, fy - 20, "1000", 15, INK, mono=True, anchor="end")
    # the right bolt (long) and the one that only looks alike (short)
    body += f'<rect x="{fx + 100}" y="{fy + 430}" width="240" height="60" fill="none" stroke="#ff5a1f" stroke-width="4"/>'
    body += f'<rect x="{fx + 365}" y="{fy + 428}" width="190" height="72" fill="none" stroke="#9a9a9a" stroke-width="2" stroke-dasharray="7 6"/>'
    body += f'<rect x="{fx + 100}" y="{fy + 392}" width="34" height="34" fill="#ff5a1f"/>' + text(
        fx + 117, fy + 416, "1", 18, WHITE, mono=True, anchor="middle"
    )
    body += text(70, 820, "long metal bolt  [152, 717, 515, 817]", 20, INK, mono=True)
    body += text(
        70, 860, "not the short one next to it: same look, other step", 18, "#5c5c5c", mono=True
    )
    return svg(
        w,
        h,
        body,
        "Muse Spark points at the long bolt on a frame, on a 0 to 1000 grid, using the context",
        "#e8e2d4",
    )


def tile_cutout() -> str:
    w, h = 800, 1000
    iso = Iso(330, 610, 6.0)
    tones = ("#ffffff", "#ffe2d6", "#ffc4ad")
    body = ""
    # grounding box around the leg on the frame, then the cut-out lifted off it
    a, b = iso.p(0, LEG, 0), iso.p(LEG, 0, LEG_H)
    body += f'<rect x="{a[0] - 30:.0f}" y="{b[1] - 30:.0f}" width="{b[0] - a[0] + 60:.0f}" height="{a[1] - b[1] + 70:.0f}" fill="none" stroke="{WHITE}" stroke-width="2" stroke-dasharray="8 7"/>'
    body += box(iso, 0, 0, 0, LEG, LEG, LEG_H, ("#ff8a5c", "#ff7a47", "#f06a36"), stroke="#b84519")
    lifted = Iso(500, 520, 6.0)
    sx, sy = lifted.p(LEG / 2, LEG / 2, 0)
    body += f'<ellipse cx="{sx:.0f}" cy="{sy + 80:.0f}" rx="70" ry="20" fill="#000" opacity=".18"/>'
    body += box(lifted, 0, 0, 0, LEG, LEG, LEG_H, tones)
    body += text(70, 880, "SAM 3.1 cut-out fills 77% of the box", 20, WHITE, mono=True)
    body += text(70, 920, "below 10%, the part is refused", 18, WHITE, mono=True, opacity=0.75)
    return svg(
        w, h, body, "SAM 3.1 cuts the leg out inside the box the agent pointed at", "#ff5a1f"
    )


def tile_check() -> str:
    w, h = 800, 1000
    rows = [
        (True, "parts B, C proven by SAM"),
        (True, "times 31.0–44.8 s fit the video"),
        (True, "result seen on frames/t44.0.jpg"),
        (True, "quote found in the narration"),
        (False, "refused: frame outside the step"),
    ]
    body = text(70, 170, 'add_step(n=3, action="insert")', 22, INK, mono=True)
    body += f'<line x1="70" y1="200" x2="730" y2="200" stroke="{INK}" stroke-opacity=".2"/>'
    for i, (ok, label) in enumerate(rows):
        y = 280 + i * 104
        if ok:
            body += f'<path d="M72 {y - 8} l12 12 l24 -26" fill="none" stroke="#1d7a3a" stroke-width="4"/>'
        else:
            body += f'<path d="M74 {y - 22} l24 24 m0 -24 l-24 24" fill="none" stroke="#bf000f" stroke-width="4"/>'
        body += text(134, y + 2, label, 26, INK if ok else "#bf000f")
        body += f'<line x1="70" y1="{y + 44}" x2="730" y2="{y + 44}" stroke="{INK}" stroke-opacity=".12"/>'
    body += text(70, 880, "checked by code, outside the model", 18, "#5c5c5c", mono=True)
    return svg(
        w,
        h,
        body,
        "Each step is checked by code outside the model; one claim is refused",
        "#fafafa",
    )


def tile_build() -> str:
    w, h = 800, 1000
    iso = Iso(400, 560, 3.6)
    body = text(70, 130, "3", 64, WHITE)
    body += text(130, 130, "/ 6", 30, WHITE, opacity=0.6)
    body += table(
        iso,
        lift=30,
        tones=("#ffffff", "#dbe9e1", "#bed6c8"),
        bolts_up=6,
        guides=True,
        stroke="#06291a",
    )
    body += letter(120, 860, "B", fill=WHITE, ink="#06291a") + text(
        150, 868, "×4", 22, WHITE, mono=True
    )
    body += letter(250, 860, "C", fill=WHITE, ink="#06291a") + text(
        280, 868, "×4", 22, WHITE, mono=True
    )
    body += text(70, 940, "Turn each bolt B into a leg C by hand.", 24, WHITE)
    return svg(
        w,
        h,
        body,
        "The guide step: turn each bolt into a leg, with the parts and counts",
        "#0f5132",
    )


DRAWINGS = {
    "hero.svg": hero,
    "identify.svg": tile_identify,
    "listen.svg": tile_listen,
    "point.svg": tile_point,
    "cutout.svg": tile_cutout,
    "check.svg": tile_check,
    "build.svg": tile_build,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in DRAWINGS.items():
        (OUT / name).write_text(draw(), encoding="utf-8")
        print(f"wrote {OUT / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
