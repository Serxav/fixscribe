# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the landing's live view: every part Spark names and SAM cuts out, one job after another.

Run: ``python -m scripts.draw_live`` -> writes web/templates/art/live.html: one SVG per job, stacked;
landing.js shows them in turn. Each part is outlined, named and listed in the order it is found.
The parts are the ``inventory`` (and the marks) make_photos kept for that photo.
"""

import json
from pathlib import Path

from scripts.draw_art import centre
from scripts.draw_mosaic import part as part_name

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = ROOT / "web" / "static" / "photos"
OUT = ROOT / "web" / "templates" / "art" / "live.html"

ORANGE = "#ff5a1f"
MONO = "JetBrains Mono, ui-monospace, Menlo, monospace"
SANS = "Inter Tight, Helvetica, Arial, sans-serif"
SIDE = 900  # the photo is a 900 x 900 square on the left of a 1600 x 900 view

JOBS = [
    ("drone", "Drone", "replace a motor"),
    ("vacuum", "Robot vacuum", "replace the brushes"),
    ("engine", "Car engine", "rebuild the head"),
]


def overlap(a: list[int], b: list[int]) -> float:
    """Intersection over the smaller box."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(1, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def parts_of(name: str) -> list[dict]:
    """Inventory first, then the job's marks that are not already in it, big parts before small."""
    data = json.loads((PHOTOS / f"{name}.json").read_text(encoding="utf-8"))
    parts = list(data.get("inventory", []))
    for mark in data["marks"]:
        kind = part_name(mark["label"])[0]
        if all(
            overlap(mark["cut_box"], p["cut_box"]) < 0.6 or kind not in p["label"].lower()
            for p in parts
        ):
            parts.append({**mark, "label": kind})
    return sorted(
        parts,
        key=lambda p: -(p["cut_box"][2] - p["cut_box"][0]) * (p["cut_box"][3] - p["cut_box"][1]),
    )


DROP = {
    "the",
    "a",
    "single",
    "each",
    "detached",
    "central",
    "drone",
    "vacuum",
    "bottom",
    "top",
    "left",
    "right",
    "leftmost",
    "rightmost",
    "first",
    "second",
    "third",
    "fourth",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "drive",
    "pc",
    "case",
}


def names(parts: list[dict]) -> list[str]:
    """Short part names without positions; repeated names are numbered (Motor 1, Motor 2...)."""
    base = []
    for part in parts:
        words = part["label"].lower().split(" closest")[0].split()
        kept = [w for w in words if w not in DROP] or words
        name = " ".join(kept)
        base.append(name[:1].upper() + name[1:])
    seen: dict[str, int] = {}
    total = {name: base.count(name) for name in base}
    out = []
    for name in base:
        if total[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            name = f"{name} {seen[name]}"
        out.append(name)
    return out


def shot(index: int, name: str, title: str, task: str) -> str:
    parts = parts_of(name)
    labels = names(parts)
    k = SIDE / 1000
    body = f'<image href="/static/photos/{name}.webp" width="{SIDE}" height="{SIDE}"/>'
    body += f'<rect width="{SIDE}" height="{SIDE}" fill="#000" opacity=".18"/>'
    taken: list[tuple[float, float, float, float]] = []
    for i, part in enumerate(parts):
        points = " ".join(f"{x * k:.0f},{y * k:.0f}" for x, y in part["outline"])
        label = labels[i]
        cx, cy = centre(part)
        lx, ly = cx * k, part["cut_box"][1] * k - 14
        width = 24 + len(label) * 9.4
        lx = min(max(8, lx - width / 2), SIDE - width - 8)
        ly = max(20, ly)
        while any(
            abs(ly - ty) < 30 and lx < tx + tw and tx < lx + width for tx, ty, tw, _ in taken
        ):
            ly += 32
        taken.append((lx, ly, width, 28))
        body += (
            f'<g class="lv-part" style="--i:{i}">'
            f'<polygon points="{points}" fill="{ORANGE}" fill-opacity=".14" stroke="{ORANGE}" stroke-width="2.5"/>'
            f'<circle cx="{cx * k:.0f}" cy="{cy * k:.0f}" r="5" fill="#fff"/>'
            f'<path d="M{cx * k:.0f} {cy * k:.0f}L{lx + width / 2:.0f} {ly + 14:.0f}" stroke="#fff" stroke-width="1.5" opacity=".8"/>'
            f'<rect x="{lx:.0f}" y="{ly - 14:.0f}" width="{width:.0f}" height="28" rx="14" fill="rgba(10,12,20,.82)"/>'
            f'<text x="{lx + 12:.0f}" y="{ly + 5:.0f}" font-family="{MONO}" font-size="15" fill="#fff">{label}</text></g>'
        )
    body += (
        f'<rect class="lv-scan" x="0" y="-60" width="900" height="60" fill="url(#lvscan{index})"/>'
    )
    body += f'<g><rect x="24" y="24" width="112" height="34" rx="17" fill="rgba(10,12,20,.75)"/><circle class="mz-glow" cx="46" cy="41" r="6" fill="#ff3b30"/><text x="60" y="47" font-family="{MONO}" font-size="15" fill="#fff">LIVE</text></g>'
    panel = f'<rect x="{SIDE}" width="700" height="900" fill="#0b1020"/>'
    panel += f'<text x="{SIDE + 56}" y="92" font-family="{MONO}" font-size="16" fill="#fff" opacity=".6">MUSE SPARK · SAM 3.1</text>'
    panel += f'<text x="{SIDE + 56}" y="150" font-family="{SANS}" font-size="44" font-weight="500" fill="#fff" letter-spacing="-0.03em">{title}</text>'
    panel += f'<text x="{SIDE + 56}" y="186" font-family="{SANS}" font-size="22" fill="#fff" opacity=".7">{task}</text>'
    rows = min(len(parts), 11)
    gap = min(56, 600 / max(1, rows))
    for i in range(rows):
        y = 252 + i * gap
        panel += (
            f'<g class="lv-row" style="--i:{i}">'
            f'<text x="{SIDE + 56}" y="{y:.0f}" font-family="{MONO}" font-size="16" fill="#fff" opacity=".5">{i + 1:02d}</text>'
            f'<text x="{SIDE + 100}" y="{y:.0f}" font-family="{SANS}" font-size="22" fill="#fff">{labels[i]}</text>'
            f'<circle cx="{SIDE + 630}" cy="{y - 7:.0f}" r="11" fill="#1d7a3a"/><path d="M{SIDE + 624} {y - 7:.0f} l4 4 l8 -9" stroke="#fff" stroke-width="2.4" fill="none"/>'
            f'<path d="M{SIDE + 56} {y + gap / 2 - 4:.0f}H{SIDE + 644}" stroke="#fff" stroke-opacity=".1"/></g>'
        )
    panel += f'<text class="lv-row" style="--i:{rows}" x="{SIDE + 56}" y="852" font-family="{MONO}" font-size="18" fill="{ORANGE}">{len(parts)} parts found · each one cut out</text>'
    return (
        f'<svg class="live-shot{" on" if index == 0 else ""}" data-i="{index}" viewBox="0 0 1600 900" preserveAspectRatio="xMinYMid slice" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Live view of a {title.lower()}: {len(parts)} parts found, named and cut out">'
        f'<defs><linearGradient id="lvscan{index}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fb2ff" stop-opacity="0"/><stop offset="1" stop-color="#0866ff" stop-opacity=".8"/></linearGradient></defs>'
        f"{body}{panel}</svg>"
    )


def main() -> int:
    OUT.write_text("\n".join(shot(i, *job) for i, job in enumerate(JOBS)) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
