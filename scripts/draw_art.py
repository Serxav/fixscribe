# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the six method illustrations of the landing as SVG over the real workshop photos.

Run: ``python -m scripts.draw_art`` -> writes web/templates/art/*.svg (inlined by the templates,
so they use the page fonts). The six drawings are the method's steps: identify,
listen, point, cut out, check, build, each shown on a different job. Every box, outline and number
comes from web/static/photos/<name>.json, the answers make_photos got from Muse Spark and SAM 3.1.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "templates" / "art"
PHOTOS = ROOT / "web" / "static" / "photos"

INK = "#0b1020"
WHITE = "#ffffff"
ORANGE = "#ff5a1f"
YELLOW = "#ffd60a"
GREEN = "#1d7a3a"
RED = "#e5202e"
FONT = "Inter Tight, Helvetica, Arial, sans-serif"
MONO = "JetBrains Mono, ui-monospace, Menlo, monospace"
W, H = 800, 1000
THIN = 'vector-effect="non-scaling-stroke"'


def text(x, y, s, size=18, fill=INK, mono=False, anchor="start", weight=400, opacity=1.0) -> str:
    family = MONO if mono else FONT
    spacing = "0" if mono else "-0.02em"
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
        f'font-weight="{weight}" letter-spacing="{spacing}" opacity="{opacity}">{s}</text>'
    )


def svg(body, label) -> str:
    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}" '
        f'preserveAspectRatio="xMidYMid slice"><rect width="{W}" height="{H}" fill="#1a1a1a"/>{body}</svg>\n'
    )


def pill(x, y, label, fill="rgba(10,12,20,.6)", ink=WHITE, size=16) -> tuple[str, float]:
    width = 24 + len(label) * size * 0.6
    out = (
        f'<rect x="{x}" y="{y}" width="{width:.0f}" height="{size * 2}" rx="{size}" fill="{fill}"/>'
    )
    out += text(x + 12, y + size * 1.36, label, size, ink, mono=True)
    return out, width


def corners(x1, y1, x2, y2, arm, color=WHITE, cls="") -> str:
    d = (
        f"M{x1} {y1 + arm}V{y1}H{x1 + arm}M{x2 - arm} {y1}H{x2}V{y1 + arm}"
        f"M{x2} {y2 - arm}V{y2}H{x2 - arm}M{x1 + arm} {y2}H{x1}V{y2 - arm}"
    )
    klass = f' class="{cls}"' if cls else ""
    return f'<path{klass} d="{d}" fill="none" stroke="{color}" stroke-width="3" {THIN} pathLength="100"/>'


def card(y, h, rows: str) -> str:
    return f'<rect x="48" y="{y}" width="704" height="{h}" rx="26" fill="{WHITE}"/>{rows}'


# --- the real marks ---------------------------------------------------------------------------


def marks_of(name: str) -> list[dict]:
    """The marks make_photos kept for photo ``name``, top to bottom then left to right."""
    data = json.loads((PHOTOS / f"{name}.json").read_text(encoding="utf-8"))
    return sorted(data["marks"], key=lambda m: (m["cut_box"][1] // 40, m["cut_box"][0]))


def view_for(
    marks: list[dict], top: float = 0.6, pad: int = 40, place: float | None = None
) -> tuple[float, float, float, float]:
    """A tile-shaped crop that fits ``marks`` in a ``top`` share of the tile, centred at ``place``."""
    x1 = min(m["cut_box"][0] for m in marks) - pad
    y1 = min(m["cut_box"][1] for m in marks) - pad
    x2 = max(m["cut_box"][2] for m in marks) + pad
    y2 = max(m["cut_box"][3] for m in marks) + pad
    h = min(1000.0, max((y2 - y1) / top, (x2 - x1) * H / W, 380.0))
    w = h * W / H
    x = min(max(0.0, (x1 + x2) / 2 - w / 2), 1000 - w)
    y = min(max(0.0, (y1 + y2) / 2 - (top / 2 if place is None else place) * h), 1000 - h)
    return x, y, w, h


def centre(mark: dict) -> tuple[float, float]:
    """The centre of SAM's cut-out (area centroid of its outline), where a ring belongs."""
    pts = mark["outline"]
    pairs = list(zip(pts, pts[1:] + pts[:1], strict=True))
    area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairs) / 2
    if abs(area) < 1:
        x1, y1, x2, y2 = mark["cut_box"]
        return (x1 + x2) / 2, (y1 + y2) / 2
    cx = sum((x1 + x2) * (x1 * y2 - x2 * y1) for (x1, y1), (x2, y2) in pairs) / (6 * area)
    cy = sum((y1 + y2) * (x1 * y2 - x2 * y1) for (x1, y1), (x2, y2) in pairs) / (6 * area)
    return cx, cy


def points(mark: dict) -> str:
    return " ".join(f"{x},{y}" for x, y in mark["outline"])


def fill_share(mark: dict) -> int:
    """How much of Spark's box SAM's outline fills (shoelace area over box area)."""
    pts = mark["outline"]
    area = (
        abs(
            sum(
                x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True)
            )
        )
        / 2
    )
    x1, y1, x2, y2 = mark["box"]
    return round(100 * area / ((x2 - x1) * (y2 - y1)))


def photo(
    name: str, view: tuple[float, float, float, float], marks: str = "", dim: float = 0.0
) -> str:
    """Photo ``name`` cropped to ``view`` (0..1000 grid), full bleed, with marks in photo units."""
    x, y, w, h = view
    shade = (
        f'<rect x="0" y="0" width="1000" height="1000" fill="#000" opacity="{dim}"/>' if dim else ""
    )
    return (
        f'<svg x="0" y="0" width="{W}" height="{H}" viewBox="{x} {y} {w} {h}" preserveAspectRatio="xMidYMid slice">'
        f'<image href="/static/photos/{name}.webp" width="1000" height="1000"/>{shade}{marks}</svg>'
    )


def to_tile(view, px, py) -> tuple[float, float]:
    """Photo grid point -> tile point for a ``view`` that fills the tile."""
    x, y, w, h = view
    return (px - x) * W / w, (py - y) * H / h


def ring(mark: dict, n: int, r: float) -> str:
    cx, cy = centre(mark)
    return (
        f'<g class="mz-ring" style="--i:{n}"><circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{YELLOW}" stroke-width="3" {THIN}/>'
        f'<circle cx="{cx + r}" cy="{cy - r}" r="{r * 0.62:.1f}" fill="{YELLOW}"/>'
        f'<text x="{cx + r}" y="{cy - r + r * 0.32:.1f}" text-anchor="middle" font-family="{MONO}" font-size="{r * 0.9:.1f}" font-weight="700" fill="{INK}">{n}</text></g>'
    )


# --- the six tiles, each on a different job ---------------------------------------------------


def tile_identify() -> str:
    marks = marks_of("panel")
    view = view_for(marks, top=0.62, pad=60)
    x1 = min(m["cut_box"][0] for m in marks)
    y1 = min(m["cut_box"][1] for m in marks)
    x2 = max(m["cut_box"][2] for m in marks)
    y2 = max(m["cut_box"][3] for m in marks)
    body = corners(x1 - 20, y1 - 20, x2 + 20, y2 + 20, 40, cls="mz-box")
    body += "".join(
        f'<polygon class="mz-glow" points="{points(m)}" fill="{RED}" fill-opacity=".3" stroke="{RED}" stroke-width="2.5" {THIN}/>'
        for m in marks
    )
    rows = text(84, 704, "MUSE SPARK · IDENTIFY", 15, "#6b6b6b", mono=True)
    lines = [
        ("Object", "Electrical panel", INK),
        ("Task", "Replace a breaker", INK),
        ("Safety", "Professional only · no steps", RED),
    ]
    for i, (key, value, color) in enumerate(lines):
        y = 762 + i * 58
        rows += (
            f'<g class="mz-in" style="--i:{i}">'
            + text(84, y, key, 22, "#6b6b6b")
            + text(230, y, value, 26, color, weight=500)
            + "</g>"
        )
        if i < 2:
            rows += f'<line x1="84" y1="{y + 22}" x2="716" y2="{y + 22}" stroke="{INK}" stroke-opacity=".08"/>'
    return svg(
        photo("panel", view, body) + card(660, 290, rows),
        "Muse Spark identifies a live electrical panel; the safety rules give no steps",
    )


def tile_listen() -> str:
    marks = marks_of("bike")
    body = photo("bike", view_for(marks, top=0.9, pad=80), dim=0.62)
    for i in range(52):
        x = 70 + i * 12.8
        v = abs(math.sin(i * 0.57) * math.cos(i * 0.19))
        bar = 14 + v * 170
        hot = 18 <= i <= 33
        delay = f"animation-delay:{(i % 7) * 0.13:.2f}s"
        body += f'<rect class="mz-level" style="{delay}" x="{x:.1f}" y="{300 - bar / 2:.1f}" width="6" height="{bar:.1f}" rx="3" fill="{YELLOW if hot else WHITE}" opacity="{1 if hot else 0.5}"/>'
    lines = [
        ("00:12.4", "Okay, smallest cog first.", False),
        ("00:15.0", "push the derailleur back", True),
        ("00:18.6", "and the wheel drops out.", False),
    ]
    for i, (stamp, words, hot) in enumerate(lines):
        y = 520 + i * 96
        body += f'<g class="mz-in" style="--i:{i}">' + text(
            70, y, stamp, 18, WHITE, mono=True, opacity=0.6
        )
        if hot:
            body += f'<rect x="198" y="{y - 34}" width="{len(words) * 15.4:.0f}" height="48" rx="6" fill="{YELLOW}"/>'
        body += text(210, y, words, 28, INK if hot else WHITE, opacity=1 if hot else 0.9) + "</g>"
    body += text(70, 880, "MUSE VOICE · timed to the second", 17, WHITE, mono=True, opacity=0.7)
    body += text(70, 914, "the quote of step 1 is found here", 17, YELLOW, mono=True)
    return svg(
        body,
        "Muse Voice transcribes a bike repair to the second; the step's quote is found in it",
    )


def tile_point() -> str:
    marks = marks_of("drone")
    motors = [m for m in marks if "motor" in m["label"].lower()]
    view = view_for(marks, top=0.8, pad=30)
    body = ""
    for m in motors:
        x1, y1, x2, y2 = m["box"]
        body += f'<rect class="mz-box" x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" fill="none" stroke="{ORANGE}" stroke-width="3.5" {THIN} pathLength="100"/>'
        cx, cy = centre(m)
        body += f'<path d="M{cx - 10} {cy}h20M{cx} {cy - 10}v20" stroke="{ORANGE}" stroke-width="2.5" {THIN}/>'
    tags = ""
    for n, m in enumerate(motors, start=1):
        tx, ty = to_tile(view, m["box"][0], m["box"][1])
        tag, _ = pill(round(tx), round(ty) - 40, str(n), fill=ORANGE, size=15)
        tags += f'<g class="mz-tag">{tag}</g>'
    x1, y1, x2, y2 = motors[0]["box"]
    rows = text(84, 868, f"motor  [{x1}, {y1}, {x2}, {y2}]", 23, INK, mono=True)
    rows += text(716, 868, "MUSE SPARK", 14, "#6b6b6b", mono=True, anchor="end")
    rows += text(84, 906, "the round motor bell only, not the leg below it", 18, "#5c5c5c")
    return svg(
        photo("drone", view, body) + tags + card(824, 124, rows),
        "Muse Spark points at the four drone motors on a 0 to 1000 grid",
    )


def tile_cutout() -> str:
    marks = marks_of("vacuum")
    brush = next(m for m in marks if "roller" in m["label"].lower())
    view = view_for(marks, top=0.62, pad=50)
    x1, y1, x2, y2 = brush["box"]
    body = (
        f'<defs><mask id="cutmask"><rect width="1000" height="1000" fill="#fff"/><polygon points="{points(brush)}" fill="#000"/></mask></defs>'
        '<rect width="1000" height="1000" fill="#000" opacity=".62" mask="url(#cutmask)"/>'
        f'<polygon class="mz-glow" points="{points(brush)}" fill="{ORANGE}" fill-opacity=".35" stroke="{ORANGE}" stroke-width="3" {THIN}/>'
        f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" fill="none" stroke="{WHITE}" stroke-width="2" stroke-dasharray="8 6" {THIN}/>'
    )
    share = fill_share(brush)
    rows = text(84, 762, "SAM 3.1", 24, INK, weight=500) + text(
        716, 762, f"{share}%", 40, INK, weight=500, anchor="end"
    )
    rows += text(84, 796, "of Spark's box is the roller brush", 18, "#5c5c5c")
    rows += f'<rect x="84" y="826" width="632" height="14" rx="7" fill="{INK}" fill-opacity=".1"/><rect class="mz-grow" x="84" y="826" width="{632 * share / 100:.0f}" height="14" rx="7" fill="{ORANGE}"/>'
    rows += f'<rect x="146" y="818" width="3" height="30" fill="{INK}"/>'
    rows += text(152, 884, "under 10%, the part is refused", 15, "#6b6b6b", mono=True)
    return svg(
        photo("vacuum", view, body) + card(710, 240, rows),
        f"SAM 3.1 cuts the robot vacuum's roller brush out inside Spark's box; it fills {share}% of it",
    )


def tile_check() -> str:
    screws = marks_of("laptop")
    view = view_for(screws, top=0.44, pad=50, place=0.76)
    body = "".join(ring(m, n, 22) for n, m in enumerate(screws, start=1))
    rows = text(84, 92, 'add_step(n=1, action="unscrew")', 21, INK, mono=True)
    rows += f'<line x1="84" y1="118" x2="716" y2="118" stroke="{INK}" stroke-opacity=".12"/>'
    checks = [
        (True, f"{len(screws)} screws proven by SAM"),
        (True, "times 08.0–21.5 s fit the video"),
        (True, "frame 12.0 s is inside the step"),
        (True, "quote found in the narration"),
        (False, f"refused: screw {len(screws) + 1} is not on the frame"),
    ]
    for i, (ok, label) in enumerate(checks):
        y = 176 + i * 62
        color = GREEN if ok else "#bf000f"
        rows += f'<g class="mz-in" style="--i:{i}"><circle cx="102" cy="{y - 8}" r="17" fill="{color}" opacity=".12"/>'
        if ok:
            rows += f'<path d="M94 {y - 8} l6 6 l12 -14" fill="none" stroke="{color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
        else:
            rows += f'<path d="M95 {y - 15} l14 14 m0 -14 l-14 14" fill="none" stroke="{color}" stroke-width="3.5" stroke-linecap="round"/>'
        rows += text(136, y, label, 22, INK if ok else color) + "</g>"
    return svg(
        photo("laptop", view, body) + card(40, 450, rows),
        "Code outside the model checks a laptop step on the real frame; one claim is refused",
    )


def tile_build() -> str:
    pegs = marks_of("guitar")
    view = view_for(pegs, top=0.55, pad=50, place=0.36)
    rings = "".join(ring(m, n, 34) for n, m in enumerate(pegs, start=1))
    body = photo("guitar", view, rings, dim=0.15)
    body += '<rect x="0" y="560" width="800" height="440" fill="url(#buildfade)"/>'
    body += '<defs><linearGradient id="buildfade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b1020" stop-opacity="0"/><stop offset=".45" stop-color="#0b1020" stop-opacity=".92"/></linearGradient></defs>'
    body += text(70, 120, "3", 72, WHITE, weight=500) + text(
        118, 120, "/ 7", 32, WHITE, opacity=0.7
    )
    body += '<g class="mz-in" style="--i:0">' + text(
        70, 790, "Loosen the six pegs", 36, WHITE, weight=500
    )
    body += text(70, 836, "until every string is slack.", 36, WHITE, weight=500) + "</g>"
    x = 70
    for i, label in enumerate((f"pegs 1–{len(pegs)}", "▶ 00:15.0", "tuned again at step 6")):
        chip, width = pill(x, 884, label, fill="rgba(255,255,255,.16)", size=15)
        body += f'<g class="mz-in" style="--i:{i + 1}">{chip}</g>'
        x += width + 12
    return svg(
        body,
        "The guide step: loosen the six tuning pegs, with the video second and where they are tuned again",
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
