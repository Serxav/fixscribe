# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the six method illustrations of the landing as SVG.

Run: ``python -m scripts.draw_art`` -> writes web/templates/art/*.svg (inlined by the templates,
so they use the page fonts). The six drawings follow one job, a phone battery swap: identify,
listen, point, cut out, check, build. The isometric helpers are shared with draw_mosaic.
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


def bolt(iso: Iso, x, y, z0, z1, color=INK) -> str:
    """A hanger bolt standing up: shaft from z0 to z1, threads as ticks."""
    a, b = iso.p(x, y, z0), iso.p(x, y, z1)
    out = f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{color}" stroke-width="{0.9 * iso.k:.1f}" stroke-linecap="round"/>'
    for i in range(1, 5):
        z = z0 + (z1 - z0) * (0.45 + i * 0.11)
        cx, cy = iso.p(x, y, z)
        out += f'<line x1="{cx - 0.8 * iso.k:.1f}" y1="{cy + 0.3 * iso.k:.1f}" x2="{cx + 0.8 * iso.k:.1f}" y2="{cy - 0.3 * iso.k:.1f}" stroke="{WHITE}" stroke-width="1"/>'
    return out


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


def phone_at(x: float, y: float, k: float, battery_class: str = "") -> str:
    """The opened phone of the mosaic, its top-left corner at (x, y), scaled by k."""
    from scripts.draw_mosaic import phone_parts

    return f'<g transform="translate({x - 109 * k:.1f} {y - 16 * k:.1f}) scale({k})">{phone_parts(battery_class)}</g>'


def corners(x0, y0, x1, y1, color=WHITE, arm=36, sw=3) -> str:
    """Viewfinder corners around a rectangle."""
    out = ""
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        out += f'<path d="M{cx} {cy + arm * dy} V{cy} H{cx + arm * dx}" fill="none" stroke="{color}" stroke-width="{sw}"/>'
    return out


def pill(x, y, label, fill="none", ink=WHITE, stroke=WHITE, size=16) -> tuple[str, float]:
    width = 22 + len(label) * size * 0.6
    out = f'<rect x="{x}" y="{y}" width="{width:.0f}" height="{size * 2}" rx="{size}" fill="{fill}" stroke="{stroke}" stroke-opacity=".6"/>'
    out += text(x + 11, y + size * 1.36, label, size, ink, mono=True)
    return out, width


def orange_box(x, y, w, h, tag="1") -> str:
    return (
        f'<rect class="mz-box" x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#ff5a1f" stroke-width="6" pathLength="100"/>'
        f'<g class="mz-tag"><rect x="{x}" y="{y - 40}" width="38" height="38" fill="#ff5a1f"/>'
        + text(x + 19, y - 12, tag, 24, WHITE, mono=True, anchor="middle")
        + "</g>"
    )


def tile_identify() -> str:
    w, h = 800, 1000
    body = phone_at(258, 92, 1.5)
    body += corners(180, 60, 620, 620)
    body += '<rect class="mz-scan" x="180" y="-90" width="440" height="60" fill="url(#idscan)"/>'
    body += '<defs><linearGradient id="idscan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity=".55"/></linearGradient></defs>'
    body += '<rect x="60" y="660" width="680" height="284" rx="26" fill="#ffffff"/>'
    body += text(92, 708, "MUSE SPARK · IDENTIFY", 15, "#6b6b6b", mono=True)
    rows = [
        ("Object", "Smartphone"),
        ("Task", "Battery swap"),
        ("Safety", "Caution · do it yourself"),
    ]
    for i, (key, value) in enumerate(rows):
        y = 760 + i * 52
        body += text(92, y, key, 20, "#6b6b6b") + text(260, y, value, 22, INK, weight=500)
        body += f'<line x1="92" y1="{y + 18}" x2="708" y2="{y + 18}" stroke="{INK}" stroke-opacity=".08"/>'
    body += f'<circle cx="636" cy="{860 - 7}" r="7" fill="#1d7a3a"/>'
    x = 92
    for hazard in ("lithium battery", "glass"):
        chip, width = pill(x, 896, hazard, fill="#fff4e5", ink="#a35a00", stroke="#a35a00", size=15)
        body += chip
        x += width + 12
    return svg(
        w,
        h,
        body,
        "Muse Spark identifies a smartphone, the battery swap task and its hazards",
        "#1b2a55",
    )


def tile_listen() -> str:
    w, h = 800, 1000
    body = ""
    for i in range(56):
        x = 70 + i * 11.8
        v = abs(math.sin(i * 0.57) * math.cos(i * 0.19))
        bar = 14 + v * 190
        hot = 20 <= i <= 35
        body += f'<rect x="{x:.1f}" y="{330 - bar / 2:.1f}" width="6" height="{bar:.1f}" rx="3" fill="{"#ffd60a" if hot else WHITE}" opacity="{1 if hot else 0.45}"/>'
    body += f'<rect x="{70 + 20 * 11.8 - 8:.0f}" y="210" width="{16 * 11.8 + 10:.0f}" height="240" rx="12" fill="#ffd60a" opacity=".08"/>'
    body += f'<line x1="70" y1="480" x2="730" y2="480" stroke="{WHITE}" stroke-opacity=".2"/>'
    lines = [
        ("00:38.5", "Okay, the screws first.", False),
        ("00:41.0", "the four little screws", True),
        ("00:44.6", "keep them in the tray.", False),
    ]
    for i, (stamp, words, hot) in enumerate(lines):
        y = 570 + i * 96
        body += text(70, y, stamp, 18, WHITE, mono=True, opacity=0.55)
        if hot:
            body += f'<rect x="198" y="{y - 34}" width="{len(words) * 15.2:.0f}" height="48" rx="6" fill="#ffd60a"/>'
        body += text(210, y, words, 28, INK if hot else WHITE, opacity=1 if hot else 0.85)
    body += text(70, 900, "MUSE VOICE · timed to the second", 17, WHITE, mono=True, opacity=0.6)
    body += text(70, 934, "the quote of step 2 is found here", 17, "#ffd60a", mono=True)
    return svg(
        w,
        h,
        body,
        "Muse Voice transcribes the narration to the second; the step's quote is found in it",
        "#121212",
    )


def tile_point() -> str:
    w, h = 800, 1000
    fx, fy, fw, fh = 70, 130, 660, 620
    body = f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="6" fill="#26303a"/>'
    body += "".join(
        f'<path d="M{fx} {fy + y} H{fx + fw}" stroke="#fff" stroke-opacity=".05"/>'
        for y in range(40, fh, 40)
    )
    body += phone_at(232, fy + 34, 1.65)
    for i in range(11):
        tx, ty = fx + fw * i / 10, fy + fh * i / 10
        body += f'<line x1="{tx:.0f}" y1="{fy - 12}" x2="{tx:.0f}" y2="{fy}" stroke="{INK}" stroke-width="1.6"/>'
        body += f'<line x1="{fx - 12}" y1="{ty:.0f}" x2="{fx}" y2="{ty:.0f}" stroke="{INK}" stroke-width="1.6"/>'
    body += text(fx, fy - 22, "0", 15, INK, mono=True) + text(
        fx + fw, fy - 22, "1000", 15, INK, mono=True, anchor="end"
    )
    # the logic board looks like a part too: Spark skips it, the step is about the battery
    bx, by = 232 - 109 * 1.65 + 198 * 1.65, fy + 34 - 16 * 1.65 + 38 * 1.65
    body += f'<rect x="{bx - 6:.0f}" y="{by - 6:.0f}" width="{68 * 1.65 + 12:.0f}" height="{110 * 1.65 + 12:.0f}" fill="none" stroke="#5b6472" stroke-width="4" stroke-dasharray="10 8"/>'
    x0, y0 = 232 - 109 * 1.65 + 132 * 1.65, fy + 34 - 16 * 1.65 + 154 * 1.65
    bw, bh = 136 * 1.65, 146 * 1.65
    body += orange_box(round(x0), round(y0), round(bw), round(bh))
    cx, cy = x0 + bw / 2, y0 + bh / 2
    body += f'<path d="M{cx - 18:.0f} {cy:.0f} h36 M{cx:.0f} {cy - 18:.0f} v36" stroke="#ff5a1f" stroke-width="3"/>'
    n = [
        round((x0 - fx) / fw * 1000),
        round((y0 - fy) / fh * 1000),
        round((x0 + bw - fx) / fw * 1000),
        round((y0 + bh - fy) / fh * 1000),
    ]
    body += text(70, 810, f"battery  [{n[0]}, {n[1]}, {n[2]}, {n[3]}]", 22, INK, mono=True)
    body += text(
        70,
        850,
        "not the logic board above it: the step is about the battery",
        17,
        "#5c5c5c",
        mono=True,
    )
    body += text(70, 930, "MUSE SPARK · points with the context", 17, "#5c5c5c", mono=True)
    return svg(
        w,
        h,
        body,
        "Muse Spark points at the battery on a frame on a 0 to 1000 grid and skips the logic board",
        "#e8e2d4",
    )


def tile_cutout() -> str:
    w, h = 800, 1000
    body = phone_at(120, 150, 1.45, battery_class="")
    bx, by = 120 + (136 - 109) * 1.45, 150 + (158 - 16) * 1.45
    bw, bh = 128 * 1.45, 138 * 1.45
    body += '<defs><pattern id="hatch" width="12" height="12" patternTransform="rotate(45)" patternUnits="userSpaceOnUse"><rect width="5" height="12" fill="#fff" opacity=".85"/></pattern></defs>'
    body += f'<rect x="{bx:.0f}" y="{by:.0f}" width="{bw:.0f}" height="{bh:.0f}" rx="10" fill="url(#hatch)" stroke="#fff" stroke-width="4"/>'
    body += f'<path d="M{bx + bw + 10:.0f} {by + 40:.0f} C 520 300, 560 260, 590 250" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="9 8"/>'
    cut = (
        '<g class="mz-lift" transform="translate(470 250) rotate(-7)">'
        '<ellipse cx="100" cy="300" rx="110" ry="16" fill="#000" opacity=".18"/>'
        f'<rect x="0" y="0" width="{bw:.0f}" height="{bh:.0f}" rx="12" fill="#c7d1f6" stroke="{INK}" stroke-width="3"/>'
        + text(24, 48, "Li-ion 3.85 V", 18, INK, mono=True, opacity=0.7)
        + f'<path d="M24 74 h130 M24 94 h90" stroke="{INK}" stroke-width="2.5" opacity=".3"/>'
        + "".join(
            f'<rect x="{x}" y="{bh - 6:.0f}" width="22" height="34" rx="4" fill="#222"/>'
            for x in (26, 136)
        )
        + "</g>"
    )
    body += cut
    body += text(70, 880, "SAM 3.1 cut-out fills 92% of the box", 22, WHITE, mono=True)
    body += text(70, 920, "below 10%, the part is refused", 18, WHITE, mono=True, opacity=0.75)
    return svg(
        w, h, body, "SAM 3.1 cuts the battery out inside the box Spark pointed at", "#ff5a1f"
    )


def tile_check() -> str:
    w, h = 800, 1000
    rows = [
        (True, "part D, the battery, proven by SAM"),
        (True, "times 44.8–58.0 s fit the video"),
        (True, "result seen on frames/t57.5.jpg"),
        (True, "quote found in the narration"),
        (False, "refused: frame outside the step"),
    ]
    body = '<rect x="50" y="110" width="700" height="760" rx="26" fill="#ffffff" stroke="#000" stroke-opacity=".06"/>'
    body += text(90, 180, 'add_step(n=3, action="remove")', 22, INK, mono=True)
    body += f'<line x1="90" y1="214" x2="710" y2="214" stroke="{INK}" stroke-opacity=".15"/>'
    for i, (ok, label) in enumerate(rows):
        y = 290 + i * 108
        color = "#1d7a3a" if ok else "#bf000f"
        body += f'<g class="mz-slide" style="--i:{i}"><circle cx="112" cy="{y - 8}" r="20" fill="{color}" opacity=".12"/>'
        if ok:
            body += f'<path d="M102 {y - 8} l7 7 l14 -16" fill="none" stroke="{color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
        else:
            body += f'<path d="M104 {y - 16} l16 16 m0 -16 l-16 16" fill="none" stroke="{color}" stroke-width="4" stroke-linecap="round"/>'
        body += text(150, y, label, 25, INK if ok else color) + "</g>"
        body += f'<line x1="90" y1="{y + 46}" x2="710" y2="{y + 46}" stroke="{INK}" stroke-opacity=".08"/>'
    body += text(70, 930, "CODE · outside the model", 17, "#5c5c5c", mono=True)
    return svg(
        w, h, body, "Code outside the model checks each step; one claim is refused", "#efeee8"
    )


def tile_build() -> str:
    w, h = 800, 1000
    body = text(70, 130, "3", 72, WHITE, weight=500) + text(122, 130, "/ 5", 32, WHITE, opacity=0.6)
    body += phone_at(268, 170, 1.3, battery_class="mz-lift")
    body += '<path d="M512 520 V380 m-16 22 l16 -22 l16 22" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
    body += text(70, 820, "Lift the battery", 34, WHITE, weight=500) + text(
        70, 864, "with the pull tabs.", 34, WHITE, weight=500
    )
    x = 70
    for label in ("D  battery ×1", "pull tabs", "00:44.8–00:58.0"):
        chip, width = pill(x, 900, label, size=15)
        body += chip
        x += width + 12
    return svg(
        w,
        h,
        body,
        "The guide step: lift the battery with the pull tabs, with its part and time",
        "#0f5132",
    )


DRAWINGS = {
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
