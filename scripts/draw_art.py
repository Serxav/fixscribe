# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the six method illustrations of the landing as SVG over the real phone photo.

Run: ``python -m scripts.draw_art`` -> writes web/templates/art/*.svg (inlined by the templates,
so they use the page fonts). The six drawings follow one job, a phone battery swap: identify,
listen, point, cut out, check, build. Every box, outline and number comes from
web/static/photos/phone.json, the answers make_photos got from Muse Spark and SAM 3.1.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "templates" / "art"
PHOTO = ROOT / "web" / "static" / "photos" / "phone.json"
HREF = "/static/photos/phone.webp"

INK = "#0b1020"
WHITE = "#ffffff"
ORANGE = "#ff5a1f"
YELLOW = "#ffd60a"
GREEN = "#1d7a3a"
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

DATA = json.loads(PHOTO.read_text(encoding="utf-8"))


def find(word: str) -> list[dict]:
    return [m for m in DATA["marks"] if word in m["label"].lower()]


BATTERY = find("battery")[0]
BRACKET = find("bracket")[0]
SCREWS = sorted(find("screw"), key=lambda m: (m["cut_box"][1] // 25, m["cut_box"][0]))
PHONE = DATA["object_box"]


def centre(mark: dict) -> tuple[float, float]:
    x1, y1, x2, y2 = mark["cut_box"]
    return (x1 + x2) / 2, (y1 + y2) / 2


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


def photo(view: tuple[float, float, float, float], marks: str = "", dim: float = 0.0) -> str:
    """The phone photo cropped to ``view`` (0..1000 grid), full bleed, with marks in photo units."""
    x, y, w, h = view
    shade = (
        f'<rect x="0" y="0" width="1000" height="1000" fill="#000" opacity="{dim}"/>' if dim else ""
    )
    return (
        f'<svg x="0" y="0" width="{W}" height="{H}" viewBox="{x} {y} {w} {h}" preserveAspectRatio="xMidYMid slice">'
        f'<image href="{HREF}" width="1000" height="1000"/>{shade}{marks}</svg>'
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


# --- the six tiles ---------------------------------------------------------------------------


def tile_identify() -> str:
    view = (100, 150, 640, 800)
    x1, y1, x2, y2 = PHONE
    marks = corners(x1, y1, x2, y2, 50, cls="mz-box")
    marks += '<rect class="mz-scan" x="100" y="60" width="640" height="90" fill="url(#idscan)"/>'
    marks += '<defs><linearGradient id="idscan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fb2ff" stop-opacity="0"/><stop offset="1" stop-color="#0866ff" stop-opacity=".7"/></linearGradient></defs>'
    rows = text(84, 704, "MUSE SPARK · IDENTIFY", 15, "#6b6b6b", mono=True)
    for i, (key, value) in enumerate(
        [
            ("Object", "Smartphone"),
            ("Task", "Battery swap"),
            ("Hazard", "Lithium battery · caution"),
        ]
    ):
        y = 762 + i * 58
        rows += (
            f'<g class="mz-in" style="--i:{i}">'
            + text(84, y, key, 22, "#6b6b6b")
            + text(250, y, value, 26, INK, weight=500)
            + "</g>"
        )
        if i < 2:
            rows += f'<line x1="84" y1="{y + 22}" x2="716" y2="{y + 22}" stroke="{INK}" stroke-opacity=".08"/>'
    return svg(
        photo(view, marks) + card(660, 290, rows),
        "Muse Spark identifies the opened smartphone, the battery swap and its hazard",
    )


def tile_listen() -> str:
    view = (100, 150, 640, 800)
    body = photo(view, dim=0.62)
    for i in range(52):
        x = 70 + i * 12.8
        v = abs(math.sin(i * 0.57) * math.cos(i * 0.19))
        bar = 14 + v * 170
        hot = 18 <= i <= 33
        delay = f"animation-delay:{(i % 7) * 0.13:.2f}s"
        body += f'<rect class="mz-level" style="{delay}" x="{x:.1f}" y="{300 - bar / 2:.1f}" width="6" height="{bar:.1f}" rx="3" fill="{YELLOW if hot else WHITE}" opacity="{1 if hot else 0.5}"/>'
    lines = [
        ("00:38.5", "Okay, the bracket first.", False),
        ("00:41.0", "the four little screws", True),
        ("00:44.6", "keep them in the tray.", False),
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
    body += text(70, 914, "the quote of step 2 is found here", 17, YELLOW, mono=True)
    return svg(
        body, "Muse Voice transcribes the narration to the second; the step's quote is found in it"
    )


def tile_point() -> str:
    view = (170, 250, 520, 650)
    x1, y1, x2, y2 = BATTERY["box"]
    bx1, by1, bx2, by2 = BRACKET["cut_box"]
    marks = f'<rect x="{bx1 - 6}" y="{by1 - 6}" width="{bx2 - bx1 + 12}" height="{by2 - by1 + 12}" fill="none" stroke="#c9ced8" stroke-width="2.5" stroke-dasharray="8 6" {THIN}/>'
    marks += f'<rect class="mz-box" x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" fill="none" stroke="{ORANGE}" stroke-width="4" {THIN} pathLength="100"/>'
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    marks += f'<path d="M{cx - 16} {cy}h32M{cx} {cy - 16}v32" stroke="{ORANGE}" stroke-width="3" {THIN}/>'
    tx, ty = to_tile(view, x1, y1)
    tag, _ = pill(round(tx), round(ty) - 44, "1 battery", fill=ORANGE, size=17)
    rows = text(84, 760, f"battery  [{x1}, {y1}, {x2}, {y2}]", 23, INK, mono=True)
    rows += text(84, 802, "not the bracket above it:", 19, "#5c5c5c")
    rows += text(84, 830, "this step is about the battery", 19, "#5c5c5c")
    rows += text(84, 900, "MUSE SPARK · 0–1000 grid", 15, "#6b6b6b", mono=True)
    return svg(
        photo(view, marks) + f'<g class="mz-tag">{tag}</g>' + card(710, 240, rows),
        "Muse Spark points at the battery on a 0 to 1000 grid and skips the bracket above it",
    )


def tile_cutout() -> str:
    view = (170, 250, 520, 650)
    x1, y1, x2, y2 = BATTERY["box"]
    marks = (
        f'<defs><mask id="cutmask"><rect width="1000" height="1000" fill="#fff"/><polygon points="{points(BATTERY)}" fill="#000"/></mask></defs>'
        '<rect width="1000" height="1000" fill="#000" opacity=".62" mask="url(#cutmask)"/>'
        f'<polygon class="mz-glow" points="{points(BATTERY)}" fill="{ORANGE}" fill-opacity=".35" stroke="{ORANGE}" stroke-width="3" {THIN}/>'
        f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" fill="none" stroke="{WHITE}" stroke-width="2" stroke-dasharray="8 6" {THIN}/>'
    )
    share = fill_share(BATTERY)
    rows = text(84, 762, "SAM 3.1", 24, INK, weight=500) + text(
        716, 762, f"{share}%", 40, INK, weight=500, anchor="end"
    )
    rows += text(84, 796, "of Spark's box is the battery", 18, "#5c5c5c")
    rows += f'<rect x="84" y="826" width="632" height="14" rx="7" fill="{INK}" fill-opacity=".1"/><rect class="mz-grow" x="84" y="826" width="{632 * share / 100:.0f}" height="14" rx="7" fill="{ORANGE}"/>'
    rows += f'<rect x="146" y="818" width="3" height="30" fill="{INK}"/>'
    rows += text(152, 884, "under 10%, the part is refused", 15, "#6b6b6b", mono=True)
    return svg(
        photo(view, marks) + card(710, 240, rows),
        f"SAM 3.1 cuts the battery out inside Spark's box; the cut-out fills {share}% of it",
    )


def tile_check() -> str:
    x1, y1, x2, y2 = BRACKET["cut_box"]
    pad = 36
    scale = 470 / (y2 - y1 + 2 * pad)
    w, h = W / scale, H / scale
    view = ((x1 + x2) / 2 - w / 2, y1 - pad, w, h)
    marks = "".join(ring(m, n, 14) for n, m in enumerate(SCREWS, start=1))
    rows = text(84, 562, 'add_step(n=2, action="unscrew")', 21, INK, mono=True)
    rows += f'<line x1="84" y1="588" x2="716" y2="588" stroke="{INK}" stroke-opacity=".12"/>'
    checks = [
        (True, f"{len(SCREWS)} screws proven by SAM"),
        (True, "times 38.5–51.0 s fit the video"),
        (True, "frame 41.0 s is inside the step"),
        (True, "quote found in the narration"),
        (False, "refused: screw 5 is not on the frame"),
    ]
    for i, (ok, label) in enumerate(checks):
        y = 646 + i * 62
        color = GREEN if ok else "#bf000f"
        rows += f'<g class="mz-in" style="--i:{i}"><circle cx="102" cy="{y - 8}" r="17" fill="{color}" opacity=".12"/>'
        if ok:
            rows += f'<path d="M94 {y - 8} l6 6 l12 -14" fill="none" stroke="{color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
        else:
            rows += f'<path d="M95 {y - 15} l14 14 m0 -14 l-14 14" fill="none" stroke="{color}" stroke-width="3.5" stroke-linecap="round"/>'
        rows += text(136, y, label, 22, INK if ok else color) + "</g>"
    return svg(
        photo(view, marks) + card(510, 450, rows),
        "Code outside the model checks each step on the real frame; one claim is refused",
    )


def tile_build() -> str:
    view = (120, 200, 520, 650)
    marks = f'<polygon points="{points(BATTERY)}" fill="{WHITE}" fill-opacity=".14" stroke="{WHITE}" stroke-width="2" {THIN}/>'
    marks += "".join(ring(m, n, 11) for n, m in enumerate(SCREWS, start=1))
    body = photo(view, marks, dim=0.25)
    body += '<rect x="0" y="560" width="800" height="440" fill="url(#buildfade)"/>'
    body += '<defs><linearGradient id="buildfade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b1020" stop-opacity="0"/><stop offset=".45" stop-color="#0b1020" stop-opacity=".92"/></linearGradient></defs>'
    body += text(70, 120, "2", 72, WHITE, weight=500) + text(
        118, 120, "/ 5", 32, WHITE, opacity=0.7
    )
    body += '<g class="mz-in" style="--i:0">' + text(
        70, 790, "Take out the four", 36, WHITE, weight=500
    )
    body += text(70, 836, "bracket screws.", 36, WHITE, weight=500) + "</g>"
    x = 70
    for i, label in enumerate((f"screws 1–{len(SCREWS)}", "▶ 00:38.5", "back in at step 9")):
        chip, width = pill(x, 884, label, fill="rgba(255,255,255,.16)", size=15)
        body += f'<g class="mz-in" style="--i:{i + 1}">{chip}</g>'
        x += width + 12
    return svg(
        body,
        "The guide step: take out the four bracket screws, with the video second and where they go back",
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
