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

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = ROOT / "web" / "static" / "photos"
OUT = ROOT / "web" / "templates" / "art" / "mosaic.html"
SMALL = 520

ORANGE = "#ff5a1f"
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


def mark_svg(mark: dict, at: float, number: int | None) -> str:
    x1, y1, x2, y2 = mark["cut_box"]
    points = " ".join(f"{x},{y}" for x, y in mark["outline"])
    body = f'<polygon class="mk-cut" points="{points}" fill="{ORANGE}" fill-opacity=".26" stroke="{ORANGE}" stroke-width="2" vector-effect="non-scaling-stroke"/>'
    body += f'<path class="mk-box" d="{corners(x1, y1, x2, y2)}" fill="none" stroke="#fff" stroke-width="2.5" vector-effect="non-scaling-stroke"/>'
    if number is not None:
        cx, cy = x2 + 8, y1 - 8
        body += f'<circle cx="{cx}" cy="{cy}" r="14" fill="{YELLOW}"/><text x="{cx}" y="{cy + 6}" text-anchor="middle" font-family="{MONO}" font-size="17" font-weight="700" fill="#111">{number}</text>'
    return f'<g class="mk" data-at="{at:.3f}">{body}</g>'


STEPS = [
    (0.2, "00:12", "Remove the back glass"),
    (0.46, "00:41", "Take out the 4 screws"),
    (0.72, "01:05", "Lift the battery out"),
]


def guide_tile() -> str:
    """The center: one video plays and each key moment becomes a checked guide step."""
    left, right = 170, 900
    span = right - left
    body = f'<rect width="1000" height="1000" fill="{BLUE}"/>'
    body += f'<text x="90" y="128" font-family="{MONO}" font-size="26" fill="#fff" opacity=".75">VIDEO · BATTERY SWAP · 01:24</text>'
    body += '<path d="M90 196 L90 244 L130 220 Z" fill="#fff"/>'
    body += (
        f'<rect x="{left}" y="214" width="{span}" height="12" rx="6" fill="#fff" opacity=".28"/>'
    )
    body += f'<rect class="mk-progress" x="{left}" y="214" width="{span}" height="12" rx="6" fill="#fff"/>'
    for n, (at, _, _) in enumerate(STEPS, start=1):
        x = left + span * at
        body += (
            f'<g class="mk" data-at="{at:.3f}"><circle cx="{x:.0f}" cy="220" r="22" fill="{YELLOW}"/>'
            f'<text x="{x:.0f}" y="229" text-anchor="middle" font-family="{MONO}" font-size="24" font-weight="700" fill="#111">{n}</text></g>'
        )
    body += f'<g class="mk-head" data-span="{span}"><circle cx="{left}" cy="220" r="15" fill="#fff"/></g>'
    for n, (at, stamp, words) in enumerate(STEPS, start=1):
        y = 320 + (n - 1) * 140
        body += (
            f'<g class="mk" data-at="{at + 0.02:.3f}"><rect x="90" y="{y}" width="820" height="116" rx="22" fill="#fff"/>'
            f'<circle cx="160" cy="{y + 58}" r="30" fill="{BLUE}"/>'
            f'<text x="160" y="{y + 69}" text-anchor="middle" font-family="{MONO}" font-size="30" font-weight="700" fill="#fff">{n}</text>'
            f'<text x="216" y="{y + 70}" font-family="Inter Tight, Helvetica, Arial, sans-serif" font-size="38" font-weight="500" fill="#0b1020" letter-spacing="-0.02em">{words}</text>'
            f'<text x="800" y="{y + 68}" text-anchor="end" font-family="{MONO}" font-size="24" fill="#6b6b6b">{stamp}</text>'
            f'<g class="mk-cut"><circle cx="856" cy="{y + 58}" r="24" fill="#1d7a3a"/>'
            f'<path d="M844 {y + 58} l9 9 l16 -18" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></g></g>'
        )
    body += '<text x="90" y="854" font-family="Inter Tight, Helvetica, Arial, sans-serif" font-size="58" font-weight="500" fill="#fff" letter-spacing="-0.03em">One video, one guide.</text>'
    body += f'<text x="90" y="910" font-family="{MONO}" font-size="26" fill="#fff" opacity=".75">every step proven by the video</text>'
    return (
        '<figure class="mz-tile" data-center>'
        '<svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="One video becomes a step-by-step guide: each key moment becomes a checked step">'
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
        fastener = part(mark["label"])[1]
        count += fastener
        at = 0.22 + i * min(0.08, 0.5 / max(1, len(marks)))
        body.append(mark_svg(mark, at, count if fastener else None))
    stops = ";".join(
        f"{(m['cut_box'][0] + m['cut_box'][2]) // 2},{(m['cut_box'][1] + m['cut_box'][3]) // 2}"
        for m in marks
    )
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
