# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Build the landing's scroll mosaic from the photos and the real marks of make_photos.

Run: ``python -m scripts.draw_mosaic`` -> writes web/templates/art/mosaic.html and a small copy of
every photo (web/static/photos/<name>-s.webp). Each tile is the photo with what Spark grounded and
SAM cut out on it: corner brackets, the cut-out outline, a number per fastener. landing.js plays
them in turn (data-at is the moment in the cycle each mark appears) and moves the aim across them.
The center tile is not a photo: one video plays and each key moment becomes a checked step.
"""

import json
from collections import Counter
from pathlib import Path

import cv2

from scripts.draw_art import centre

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = ROOT / "web" / "static" / "photos"
OUT = ROOT / "web" / "templates" / "art" / "mosaic.html"
SMALL = 520

ORANGE = "#ff5a1f"
RED = "#ff2d3a"
YELLOW = "#ffd60a"
BLUE = "#0866ff"
MONO = "JetBrains Mono, ui-monospace, Menlo, monospace"

# Grid order: 7 columns x 3 rows on desktop (3 x 7 on a phone); the guide (index 10) is the center.
TILES = [
    ("laptop", "Laptop", "laptop"),
    ("chair", "Office chair", "chair"),
    ("bike", "Bicycle", "bike"),
    ("engine", "Car engine", "engine"),
    ("washer", "Washing machine", "washer"),
    ("panel", "Electrical panel", "mains panel"),
    ("drone", "Drone", "drone"),
    ("faucet", "Faucet", "faucet"),
    ("wheel", "Car wheel", "wheel"),
    ("pc", "Desktop computer", "PC"),
    ("guide", "", ""),
    ("drill", "Drill", "drill"),
    ("coffee", "Coffee machine", "coffee"),
    ("guitar", "Guitar", "guitar"),
    ("controller", "Game controller", "controller"),
    ("shelf", "Bookshelf", "shelf"),
    ("lamp", "Desk lamp", "lamp"),
    ("aircon", "Air conditioner", "AC gas"),
    ("boiler", "Gas boiler", "gas boiler"),
    ("vacuum", "Robot vacuum", "vacuum"),
    ("table", "Side table", "table"),
]
CENTER = 10

# What a grounded label is called on the page, and whether it is a fastener (gets a number).
PARTS = [
    ("breaker", "breaker row", False),
    ("service valve", "service valve", False),
    ("gas valve", "gas valve", False),
    ("refrigerant lin", "refrigerant line", False),
    ("portafilter", "portafilter", False),
    ("side brush", "side brush", False),
    ("roller", "roller brush", False),
    ("hub", "wheel hub", False),
    ("bracket", "bracket", False),
    ("socket", "bulb socket", False),
    ("lug nut", "lug nut", True),
    ("cam lock", "cam lock", True),
    ("cam bolt", "cam bolt", True),
    ("screw", "screw", True),
    ("bolt", "bolt", True),
    ("stud", "stud", True),
    ("peg", "tuning peg", True),
    ("graphics", "graphics card", False),
    ("ram", "RAM", False),
    ("stick", "stick module", False),
    ("motor", "motor", False),
    ("battery", "battery", False),
    ("tabletop", "tabletop", False),
    ("leg", "leg", False),
    ("shade", "lamp shade", False),
    ("cartridge", "cartridge", False),
    ("chuck", "chuck", False),
    ("tank", "water tank", False),
    ("gas lift", "gas lift", False),
    ("derailleur", "derailleur", False),
    ("cassette", "cassette", False),
    ("filter", "drain filter", False),
    ("cylinder", "lock cylinder", False),
]


def part(label: str) -> tuple[str, bool]:
    """The part a grounded label names: the known word that comes first in it."""
    low = label.lower()
    hits = [
        (low.find(key), -len(key), name, fastener) for key, name, fastener in PARTS if key in low
    ]
    if not hits:
        return low, False
    _, _, name, fastener = min(hits)
    return name, fastener


def plural(name: str, count: int) -> str:
    return name if count == 1 else name + "s"


def chip_text(short: str, marks: list[dict], refused: bool) -> str:
    if refused:
        return f"{short} · refused"
    counts = Counter(part(m["label"]) for m in marks)
    words = [
        f"{count} {plural(name, count)}" if fastener or count > 1 else name
        for (name, fastener), count in sorted(counts.items(), key=lambda kv: (not kv[0][1], -kv[1]))
    ]
    return " · ".join([short, *words[:2]])


def corners(x1: int, y1: int, x2: int, y2: int, pad: int = 6) -> str:
    x1, y1, x2, y2 = x1 - pad, y1 - pad, x2 + pad, y2 + pad
    arm = max(8, min(40, (x2 - x1) // 4, (y2 - y1) // 4))
    return (
        f"M{x1} {y1 + arm}V{y1}H{x1 + arm}M{x2 - arm} {y1}H{x2}V{y1 + arm}"
        f"M{x2} {y2 - arm}V{y2}H{x2 - arm}M{x1 + arm} {y2}H{x1}V{y2 - arm}"
    )


def mark_svg(mark: dict, at: float, number: int | None, color: str = ORANGE) -> str:
    """One mark; a hazard on a refused job is drawn in red."""
    x1, y1, x2, y2 = mark["cut_box"]
    points = " ".join(f"{x},{y}" for x, y in mark["outline"])
    body = f'<polygon class="mk-cut" points="{points}" fill="{color}" fill-opacity=".26" stroke="{color}" stroke-width="2" vector-effect="non-scaling-stroke"/>'
    body += f'<path class="mk-box" d="{corners(x1, y1, x2, y2)}" fill="none" stroke="#fff" stroke-width="2.5" vector-effect="non-scaling-stroke"/>'
    if number is not None:
        cx, cy = x2 + 8, y1 - 8
        body += f'<circle cx="{cx}" cy="{cy}" r="14" fill="{YELLOW}"/><text x="{cx}" y="{cy + 6}" text-anchor="middle" font-family="{MONO}" font-size="17" font-weight="700" fill="#111">{number}</text>'
    return f'<g class="mk" data-at="{at:.3f}">{body}</g>'


# The center: four layers of one job, a gadget with two knobs and four screws, in its own units.
KNOBS = [(-80, 0, 52), (80, 0, 52)]
SCREWS = [(-150, -88), (150, -88), (-150, 88), (150, 88)]
LAYERS = [
    ("04", "Guide", "Muse Wonder"),
    ("03", "Cut out", "SAM 3.1"),
    ("02", "Point", "Muse Spark"),
    ("01", "Video", "Muse Voice"),
]
ISO = "matrix(0.5 0.29 -0.5 0.29 {x} {y})"
INK = "#0b1020"
SANS = "Inter Tight, Helvetica, Arial, sans-serif"


def gadget() -> str:
    body = '<rect x="-190" y="-120" width="380" height="240" rx="34" fill="#d9dde5"/>'
    body += '<rect x="-190" y="-120" width="380" height="240" rx="34" fill="none" stroke="#fff" stroke-width="4" opacity=".6"/>'
    body += "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="#3a4357"/><circle cx="{x}" cy="{y}" r="{r * 0.45:.0f}" fill="#58627a"/>'
        for x, y, r in KNOBS
    )
    body += "".join(
        f'<circle cx="{x}" cy="{y}" r="11" fill="#9aa3b5"/><path d="M{x - 6} {y}h12" stroke="#3a4357" stroke-width="3"/>'
        for x, y in SCREWS
    )
    return body


def layer(index: int) -> str:
    """One plane drawn flat in -250..250 units; the iso matrix lays it down."""
    if index == 3:
        body = f'<rect x="-250" y="-250" width="500" height="500" rx="28" fill="{INK}"/>' + gadget()
        body += '<path d="M-200 175 L-200 215 L-166 195 Z" fill="#fff"/><rect x="-140" y="190" width="330" height="10" rx="5" fill="#fff" opacity=".3"/><rect x="-140" y="190" width="150" height="10" rx="5" fill="#fff"/>'
        body += "".join(
            f'<rect x="{-200 + i * 14}" y="{-215 - h / 2:.0f}" width="7" height="{h:.0f}" rx="3" fill="{YELLOW}"/>'
            for i, h in enumerate(10 + 28 * abs(((i * 37) % 11) - 5) / 5 for i in range(29))
        )
    elif index == 2:
        body = '<rect x="-250" y="-250" width="500" height="500" rx="28" fill="#fff" fill-opacity=".1" stroke="#fff" stroke-width="3" stroke-dasharray="14 10"/>'
        for x, y, r in KNOBS:
            body += corners(x - r, y - r, x + r, y + r, pad=8).join(
                ['<path d="', '" fill="none" stroke="#fff" stroke-width="7"/>']
            )
        for x, y in SCREWS:
            body += f'<rect x="{x - 18}" y="{y - 18}" width="36" height="36" fill="none" stroke="#fff" stroke-width="5"/>'
    elif index == 1:
        body = '<rect x="-250" y="-250" width="500" height="500" rx="28" fill="#fff" fill-opacity=".1" stroke="#fff" stroke-width="3" stroke-dasharray="14 10"/>'
        body += "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{ORANGE}"/>' for x, y, r in KNOBS)
        body += "".join(f'<circle cx="{x}" cy="{y}" r="13" fill="{ORANGE}"/>' for x, y in SCREWS)
    else:
        body = '<rect x="-250" y="-250" width="500" height="500" rx="28" fill="#fff"/>'
        for n in range(3):
            y = -150 + n * 120
            body += f'<circle cx="-170" cy="{y}" r="34" fill="{BLUE}"/><text x="-170" y="{y + 15}" text-anchor="middle" font-family="{MONO}" font-size="42" font-weight="700" fill="#fff">{n + 1}</text>'
            body += f'<rect x="-110" y="{y - 26}" width="{250 - n * 40}" height="20" rx="10" fill="{INK}" opacity=".85"/><rect x="-110" y="{y + 8}" width="{170 - n * 30}" height="14" rx="7" fill="{INK}" opacity=".3"/>'
            body += f'<circle cx="180" cy="{y}" r="30" fill="#1d7a3a"/><path d="M165 {y} l11 11 l20 -22" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>'
    return body


def guide_tile() -> str:
    """The center: one job as four layers that fan apart, one per Meta model."""
    cx, gap = 650, 178
    body = f'<rect width="1000" height="1000" fill="{BLUE}"/>'
    for index, (number, name, model) in reversed(list(enumerate(LAYERS))):
        y = 200 + index * gap
        spread = (index - 1.5) * 22
        label_y = y + 4
        body += (
            f'<g class="lay" style="--from:{-spread:.0f}px;--to:{spread:.0f}px">'
            f'<g transform="{ISO.format(x=cx, y=y)}">{layer(index)}</g>'
            f'<path d="M{cx - 400} {y}H{cx - 262}" stroke="#fff" stroke-width="2" opacity=".5"/>'
            f'<text x="56" y="{label_y}" font-family="{MONO}" font-size="24" fill="#fff" opacity=".7">{number}</text>'
            f'<text x="100" y="{label_y}" font-family="{SANS}" font-size="34" font-weight="500" fill="#fff" letter-spacing="-0.02em">{name}</text>'
            f'<text x="100" y="{label_y + 34}" font-family="{MONO}" font-size="21" fill="#fff" opacity=".75">{model}</text></g>'
        )
    body += f'<text x="56" y="964" font-family="{SANS}" font-size="44" font-weight="500" fill="#fff" letter-spacing="-0.03em">One video in, a proven guide out.</text>'
    return (
        '<figure class="mz-tile" data-center>'
        '<svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="One job in four layers: the video, the parts Muse Spark points at, the cut-outs of SAM 3.1 and the guide Muse Wonder writes">'
        f"{body}</svg></figure>"
    )


def tile(name: str, title: str, short: str) -> str:
    data = json.loads((PHOTOS / f"{name}.json").read_text(encoding="utf-8"))
    marks, refused = data["marks"], data.get("refused", False)
    href = f"/static/photos/{name}-s.webp"
    marks = sorted(
        marks, key=lambda m: (part(m["label"])[1], m["cut_box"][1] // 60, m["cut_box"][0])
    )
    body = []
    count = 0
    for i, mark in enumerate(marks):
        fastener = part(mark["label"])[1] and not refused
        count += fastener
        at = 0.22 + i * min(0.08, 0.5 / max(1, len(marks)))
        body.append(mark_svg(mark, at, count if fastener else None, RED if refused else ORANGE))
    stops = ";".join("{:.0f},{:.0f}".format(*centre(m)) for m in marks)
    aim = (
        f'<g class="mk-aim" data-stops="{stops}"><circle r="34" fill="none" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke"/>'
        '<path d="M-52 0H-22M22 0H52M0 -52V-22M0 22V52" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke"/></g>'
        if marks
        else ""
    )
    chip = chip_text(short, marks, refused)
    label = f"{title}: " + (
        "professional only, no steps given"
        if refused
        else " and ".join(chip.split(" · ")[1:]) + " found"
    )
    scan = (
        '<rect class="mk-scan" x="0" y="-120" width="1000" height="120" fill="url(#mks)"/>'
        if not refused
        else ""
    )
    return (
        '<figure class="mz-tile">'
        f'<svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">'
        f'<image href="{href}" width="1000" height="1000" preserveAspectRatio="xMidYMid slice"/>'
        f"{''.join(body)}{aim}{scan}"
        "</svg></figure>"
    )


DEFS = (
    '<svg width="0" height="0" aria-hidden="true" style="position:absolute"><defs>'
    '<linearGradient id="mks" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fb2ff" stop-opacity="0"/>'
    f'<stop offset=".9" stop-color="#7fb2ff" stop-opacity=".28"/><stop offset="1" stop-color="{BLUE}" stop-opacity=".95"/></linearGradient>'
    "</defs></svg>"
)


def small_copies() -> None:
    for name, _, _ in TILES:
        if name == "guide":
            continue
        image = cv2.imread(str(PHOTOS / f"{name}.webp"))
        small = cv2.resize(image, (SMALL, SMALL), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(PHOTOS / f"{name}-s.webp"), small, [cv2.IMWRITE_WEBP_QUALITY, 84])


def mosaic() -> str:
    figures = [guide_tile() if i == CENTER else tile(*row) for i, row in enumerate(TILES)]
    return DEFS + '\n<div class="mz-grid" data-mosaic>\n' + "\n".join(figures) + "\n</div>\n"


def main() -> int:
    small_copies()
    OUT.write_text(mosaic(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
