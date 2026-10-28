# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the app screens shown in the landing's "What FixScribe does" section.

Run: ``python -m scripts.draw_screens`` -> writes web/templates/art/screens.html: one SVG phone
screen per feature, stacked; landing.js shows the one whose text is on screen. Each screen is a
faithful sketch of a real page of the app (record, progress, guide, reverse guide, check my step,
live coach, film) plus one marked "coming next" (replace a part). Every photo inside a screen is
the same opened phone as the mosaic, and every mark sits on its real screws and battery.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "templates" / "art" / "screens.html"
W, H = 360, 760
INK = "#161616"
MUTED = "#6b6b6b"
SURFACE = "#f6f5f1"
CARD = "#ecebe5"
GREEN = "#1d7a3a"
FONT = "Inter Tight, Helvetica, Arial, sans-serif"
MONO = "JetBrains Mono, ui-monospace, Menlo, monospace"
ORANGE = "#ff5a1f"
YELLOW = "#ffd60a"
RED = "#e5202e"
LINE = "#0b1020"

# The real phone photo (the mosaic's center) and the marks Spark and SAM 3.1 found on it.
PHOTO = json.loads(
    (Path(__file__).resolve().parents[1] / "web" / "static" / "photos" / "phone.json").read_text(
        encoding="utf-8"
    )
)
HREF = "/static/photos/phone.webp"
# The photo region shown as "the phone": its frame is (109, 16)-(291, 346) in screen units at k=1.
VIEW = (148, 0, 551, 1000)
FRAME = (109, 16, 182, 330)


def from_photo(gx: float, gy: float) -> tuple[float, float]:
    """A point on the photo's 0..1000 grid -> the phone frame's own units."""
    return (
        FRAME[0] + (gx - VIEW[0]) * FRAME[2] / VIEW[2],
        FRAME[1] + (gy - VIEW[1]) * FRAME[3] / VIEW[3],
    )


def _marks(word: str) -> list[dict]:
    return [m for m in PHOTO["marks"] if word in m["label"].lower().split(" on ")[0]]


_BATTERY = _marks("battery")[0]
BATTERY = (*from_photo(*_BATTERY["box"][:2]), *from_photo(*_BATTERY["box"][2:]))
SCREWS = [
    from_photo((m["cut_box"][0] + m["cut_box"][2]) / 2, (m["cut_box"][1] + m["cut_box"][3]) / 2)
    for m in sorted(_marks("screw"), key=lambda m: (m["cut_box"][1] // 25, m["cut_box"][0]))
]
_ids = iter(range(1, 1000))


def ring(x, y, n, r=11) -> str:
    """A numbered fastener ring (mz-ring pulses in turn by --i)."""
    return (
        f'<g class="mz-ring" style="--i:{n}"><circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{YELLOW}" stroke-width="3.5"/>'
        f'<circle cx="{x + r}" cy="{y - r}" r="9" fill="{YELLOW}"/>'
        f'<text x="{x + r}" y="{y - r + 4.5}" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{LINE}">{n}</text></g>'
    )


def t(x, y, s, size=15, fill=INK, mono=False, weight=400, anchor="start", opacity=1.0) -> str:
    family = MONO if mono else FONT
    spacing = "0" if mono else "-0.02em"
    return f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" letter-spacing="{spacing}" opacity="{opacity}">{s}</text>'


def status_bar(dark=False) -> str:
    c = "#fff" if dark else INK
    return (
        t(26, 30, "9:41", 14, c, weight=500)
        + f'<rect x="300" y="19" width="26" height="12" rx="3" fill="none" stroke="{c}" stroke-width="1.4"/><rect x="302" y="21" width="18" height="8" rx="1.5" fill="{c}"/>'
    )


def header(title: str) -> str:
    glyph = f'<rect x="24" y="58" width="9" height="3.5" fill="{INK}"/><rect x="24" y="64" width="15" height="3.5" fill="{INK}"/><rect x="24" y="70" width="22" height="3.5" fill="{INK}"/>'
    return glyph + t(54, 72, title, 16, weight=500)


class Phone:
    """The mosaic's opened phone placed on a screen: top-left corner (x, y), scale k."""

    def __init__(self, x: float, y: float, k: float) -> None:
        self.x, self.y, self.k = x, y, k

    def at(self, px: float, py: float) -> tuple[float, float]:
        return self.x + (px - 109) * self.k, self.y + (py - 16) * self.k

    def draw(self, battery_class: str = "") -> str:
        """The photo of the opened phone; with ``battery_class`` its battery cut-out moves on top."""
        tx, ty = self.x - 109 * self.k, self.y - 16 * self.k
        n = next(_ids)
        x, y, w, h = FRAME
        view = " ".join(str(v) for v in VIEW)
        battery = ""
        if battery_class:
            points = " ".join(f"{px},{py}" for px, py in _BATTERY["outline"])
            battery = (
                f'<clipPath id="bat{n}"><polygon points="{points}"/></clipPath>'
                f'<g class="{battery_class}"><image href="{HREF}" width="1000" height="1000" clip-path="url(#bat{n})"/>'
                f'<polygon points="{points}" fill="none" stroke="#fff" stroke-width="1.5" vector-effect="non-scaling-stroke"/></g>'
            )
        return (
            f'<g transform="translate({tx:.1f} {ty:.1f}) scale({self.k})">'
            f'<clipPath id="ph{n}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22"/></clipPath>'
            f'<g clip-path="url(#ph{n})"><svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{view}" preserveAspectRatio="none">'
            f'<image href="{HREF}" width="1000" height="1000"/>{battery}</svg></g></g>'
        )

    def battery_box(self, pad: float = 5, tag: str = "1") -> str:
        (x0, y0), (x1, y1) = self.at(BATTERY[0], BATTERY[1]), self.at(BATTERY[2], BATTERY[3])
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        return (
            f'<rect class="mz-box" x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" fill="none" stroke="{ORANGE}" stroke-width="3.5" pathLength="100"/>'
            f'<g class="mz-tag"><rect x="{x0:.1f}" y="{y0 - 22:.1f}" width="22" height="22" fill="{ORANGE}"/>'
            + t(round(x0 + 11, 1), round(y0 - 6, 1), tag, 14, "#fff", mono=True, anchor="middle")
            + "</g>"
        )


def corners(x0, y0, x1, y1, color="#fff", arm=22, sw=2.5) -> str:
    out = ""
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        out += f'<path d="M{cx} {cy + arm * dy} V{cy} H{cx + arm * dx}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-opacity=".8"/>'
    return out


def screen(i: int, label: str, body: str, bg=SURFACE) -> str:
    return (
        f'<svg class="screen" data-i="{i}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">'
        f'<rect width="{W}" height="{H}" fill="{bg}"/>{body}</svg>'
    )


# --- the screens ------------------------------------------------------------------------------


def record() -> str:
    b = '<rect x="0" y="0" width="360" height="616" fill="#2f5d50"/>'
    b += "".join(
        f'<path d="M{x} 0 V616" stroke="#fff" stroke-opacity=".07"/>' for x in range(30, 360, 30)
    )
    b += "".join(
        f'<path d="M0 {y} H360" stroke="#fff" stroke-opacity=".07"/>' for y in range(30, 616, 30)
    )
    phone = Phone(100, 150, 0.88)
    b += '<ellipse cx="180" cy="452" rx="92" ry="10" fill="#000" opacity=".18"/>' + phone.draw()
    b += corners(28, 96, 332, 520)
    b += f'<rect x="124" y="56" width="112" height="30" rx="15" fill="{RED}"/><circle class="mz-glow" cx="142" cy="71" r="5" fill="#fff"/>'
    b += t(186, 76, "REC 00:42", 13, "#fff", mono=True, anchor="middle")
    for i, (label, x) in enumerate((("step 1 · 00:12", 24), ("step 2 · 00:41", 160))):
        b += (
            f'<g class="mz-in" style="--i:{i}"><rect x="{x}" y="542" width="124" height="26" rx="13" fill="#000" fill-opacity=".45"/>'
            + t(x + 62, 559, label, 11.5, "#fff", mono=True, anchor="middle")
            + "</g>"
        )
    b += t(
        180,
        596,
        "Say each step out loud — or stay silent.",
        13,
        "#fff",
        anchor="middle",
        opacity=0.85,
    )
    b += '<rect x="0" y="616" width="360" height="144" fill="#0e0e0e"/>'
    b += f'<circle cx="180" cy="684" r="34" fill="none" stroke="#fff" stroke-width="4"/><rect class="mz-glow" x="166" y="670" width="28" height="28" rx="6" fill="{RED}"/>'
    b += t(60, 689, "Upload", 13, "#fff", anchor="middle", opacity=0.75) + t(
        300, 689, "1×", 13, "#fff", anchor="middle", opacity=0.75
    )
    b += status_bar(dark=True)
    return screen(
        0, "Recording a repair video in FixScribe; each spoken step is marked", b, "#0e0e0e"
    )


def recognize() -> str:
    b = status_bar() + header("Making your guide")
    b += f'<rect x="20" y="96" width="320" height="150" rx="16" fill="{CARD}"/>'
    b += (
        '<rect x="36" y="112" width="76" height="118" rx="10" fill="#1b2233"/>'
        + Phone(44.5, 117, 0.33).draw()
    )
    b += t(128, 136, "Smartphone", 20, weight=500) + t(
        128, 158, "electronics · repair", 13, MUTED, mono=True
    )
    x = 128
    for chip in ("lithium battery", "glass"):
        width = 16 + len(chip) * 7.4
        b += (
            f'<rect x="{x}" y="174" width="{width:.0f}" height="24" rx="12" fill="#fff4e5" stroke="#a35a00" stroke-opacity=".45"/>'
            + t(x + 8, 190, chip, 11.5, "#a35a00", mono=True)
        )
        x += width + 8
    b += f'<circle cx="133" cy="217" r="4" fill="{GREEN}"/>' + t(
        143, 221, "caution · do it yourself", 12, GREEN
    )
    for i in range(46):
        h = 8 + (abs(((i * 37) % 23) - 11)) * 2.2
        b += f'<rect x="{24 + i * 6.9:.1f}" y="{300 - h / 2:.1f}" width="3" height="{h:.1f}" rx="1.5" fill="{INK if 14 < i < 30 else "#b9b8b2"}"/>'
    b += t(24, 346, "“Take out the four little screws first…”", 14, INK)
    b += t(24, 366, "00:41.0 · Muse Voice", 12, MUTED, mono=True)
    stages = [
        ("Identify", "Muse Spark", "done"),
        ("Listen", "Muse Voice", "done"),
        ("Point at each part", "Muse Spark", "run"),
        ("Cut out and check", "SAM 3.1", "wait"),
        ("Write the guide", "Muse Wonder", "wait"),
    ]
    for i, (name, model, state) in enumerate(stages):
        y = 420 + i * 58
        b += f'<path d="M20 {y - 22} H340" stroke="{INK}" stroke-opacity=".12"/>'
        if state == "done":
            b += f'<circle cx="34" cy="{y - 5}" r="9" fill="{GREEN}"/><path d="M29 {y - 5} l4 4 l7 -8" stroke="#fff" stroke-width="2" fill="none"/>'
        elif state == "run":
            b += f'<circle class="mz-glow" cx="34" cy="{y - 5}" r="9" fill="#0866ff"/>'
        else:
            b += f'<circle cx="34" cy="{y - 5}" r="8" fill="none" stroke="{MUTED}" stroke-width="1.5"/>'
        b += t(56, y, name, 16, INK if state != "wait" else MUTED) + t(
            340, y, model, 12, MUTED, mono=True, anchor="end"
        )
    b += f'<rect x="20" y="712" width="320" height="6" rx="3" fill="{CARD}"/><rect class="mz-grow" x="20" y="712" width="200" height="6" rx="3" fill="{INK}"/>'
    return screen(1, "FixScribe recognizing the object and the task while it builds the guide", b)


def guide() -> str:
    b = status_bar() + header("Replace the battery")
    b += t(24, 106, "5 steps · 92% proven · 25 min", 13, MUTED, mono=True)
    b += '<rect x="20" y="122" width="320" height="260" rx="14" fill="#1b2233"/>'
    phone = Phone(116, 136, 0.7)
    b += phone.draw()
    for i, (sx, sy) in enumerate(SCREWS, start=1):
        x, y = phone.at(sx, sy)
        b += ring(round(x, 1), round(y, 1), i, r=7)
    b += (
        t(24, 414, "STEP 2", 12, MUTED, mono=True)
        + t(24, 444, "Remove the four screws", 22, weight=500)
        + t(24, 470, "that hold the battery bracket.", 22, weight=500)
    )
    b += (
        f'<rect x="24" y="490" width="312" height="52" rx="10" fill="{CARD}"/>'
        + t(38, 513, "“the four little screws”", 15)
        + t(38, 532, "you, at 00:41", 12, MUTED, mono=True)
    )
    b += f'<path d="M20 566 H340" stroke="{INK}" stroke-opacity=".12"/>' + t(24, 592, "Proof", 15)
    for i, c in enumerate((GREEN, GREEN, "#a35a00")):
        b += f'<circle cx="{298 + i * 14}" cy="587" r="5" fill="{c}"/>'
    b += (
        f'<rect x="20" y="618" width="154" height="46" rx="10" fill="none" stroke="{INK}" stroke-opacity=".2"/>'
        + t(97, 646, "Watch in video", 14, anchor="middle")
    )
    b += f'<rect x="186" y="618" width="154" height="46" rx="10" fill="{INK}"/>' + t(
        263, 646, "Check this step", 14, "#fff", anchor="middle"
    )
    return screen(
        2, "A FixScribe guide step with the four screws numbered, the quote and its proof", b
    )


def reverse() -> str:
    b = status_bar() + header("Replace the battery")
    b += f'<rect x="20" y="96" width="320" height="40" rx="20" fill="{CARD}"/><rect x="184" y="100" width="152" height="32" rx="16" fill="{INK}"/>'
    b += t(102, 121, "Take apart", 14, anchor="middle") + t(
        260, 121, "Put back", 14, "#fff", anchor="middle"
    )
    steps = [
        ("Place the new battery", "battery"),
        ("Reconnect the flex cable", "connector"),
        ("Screw in the four screws", "4 screws back"),
        ("Close the back cover", "cover"),
        ("Power on and test", ""),
    ]
    for i, (text, part) in enumerate(steps):
        y = 182 + i * 92
        b += f'<g class="mz-in" style="--i:{i}"><path d="M20 {y - 26} H340" stroke="{INK}" stroke-opacity=".12"/>'
        b += t(24, y, f"0{i + 1}", 13, MUTED, mono=True) + t(64, y, text, 18)
        if part:
            b += t(64, y + 24, part, 12, MUTED, mono=True)
        b += "</g>"
    b += f'<rect x="20" y="650" width="320" height="64" rx="14" fill="#e3f1e7"/><circle cx="48" cy="682" r="11" fill="{GREEN}"/><path d="M42 682 l4 4 l8 -9" stroke="#fff" stroke-width="2.2" fill="none"/>'
    b += t(70, 678, "Screws: 4 out · 4 back", 15, GREEN, weight=500) + t(
        70, 698, "every fastener accounted for", 12, GREEN, mono=True
    )
    return screen(3, "The reverse guide: put it back together, with every screw accounted for", b)


def check() -> str:
    b = '<rect x="0" y="0" width="360" height="760" fill="#2b2b2b"/>'
    phone = Phone(51, 104, 1.42)
    b += phone.draw()
    for i, (sx, sy) in enumerate(SCREWS):
        x, y = phone.at(sx, sy)
        if i >= 2:
            b += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="#0e3b22" fill-opacity=".55" stroke="#7ee2a0" stroke-width="3"/><path d="M{x - 6:.1f} {y:.1f} l4 4 l8 -9" stroke="#7ee2a0" stroke-width="2.5" fill="none"/>'
        else:
            b += f'<circle class="mz-glow" cx="{x:.1f}" cy="{y:.1f}" r="15" fill="none" stroke="#ff8a80" stroke-width="3.5"/>'
    b += t(24, 82, "Check this step · SAM 3.1", 13, "#fff", mono=True, opacity=0.8)
    b += f'<rect x="16" y="664" width="328" height="76" rx="14" fill="{INK}"/><circle cx="44" cy="702" r="7" fill="#ffb340"/>'
    b += t(62, 697, "Not yet", 16, "#fff", weight=500) + t(
        62, 718, "2 screws are still in place, at the top.", 13, "#fff", opacity=0.8
    )
    b += status_bar(dark=True)
    return screen(
        4, "Check my step: a photo of your own phone, two screws still in place", b, "#0e0e0e"
    )


def live() -> str:
    b = '<rect x="0" y="0" width="360" height="760" fill="#24302b"/>'
    phone = Phone(89, 112, 1.0)
    b += phone.draw(battery_class="mz-lift")
    b += corners(40, 96, 320, 470)
    b += (
        t(24, 82, "Live coach", 13, "#fff", mono=True, opacity=0.8)
        + '<circle class="mz-glow" cx="326" cy="77" r="6" fill="#30d158"/>'
    )
    b += '<rect x="14" y="512" width="332" height="224" rx="22" fill="#1c1c1e" fill-opacity=".92"/>'
    b += t(34, 548, "STEP 3 OF 5", 12, "#fff", mono=True, opacity=0.7) + t(
        326, 548, "ON TRACK", 12, "#30d158", mono=True, anchor="end"
    )
    b += t(34, 588, "Lift the battery", 24, "#fff", weight=500) + t(
        34, 618, "with the pull tabs.", 24, "#fff", weight=500
    )
    b += t(34, 654, "Next: disconnect the flex cable", 14, "#fff", opacity=0.7)
    for i in range(14):
        h = 6 + (abs(((i * 29) % 13) - 6)) * 2.4
        b += f'<rect class="mz-glow" x="{34 + i * 7}" y="{700 - h / 2:.1f}" width="3" height="{h:.1f}" rx="1.5" fill="#fff" style="animation-delay:{i * 0.09:.2f}s"/>'
    b += t(150, 704, "speaking", 12, "#fff", mono=True, opacity=0.6)
    b += status_bar(dark=True)
    return screen(
        5,
        "Live coach: the camera sees your work and says which step you are on and what comes next",
        b,
        "#24302b",
    )


def film() -> str:
    b = '<rect x="0" y="0" width="360" height="760" fill="#0e0e0e"/><rect x="0" y="112" width="360" height="440" fill="#1b2233"/>'
    phone = Phone(80, 128, 1.1)
    b += phone.draw() + phone.battery_box()
    b += t(24, 82, "Replace the battery · film", 13, "#fff", mono=True, opacity=0.8)
    b += (
        '<rect x="24" y="486" width="312" height="48" rx="10" fill="#000" fill-opacity=".72"/>'
        + t(180, 516, "Lift the battery with the pull tabs.", 14, "#fff", anchor="middle")
    )
    b += '<rect x="24" y="584" width="312" height="4" rx="2" fill="#fff" fill-opacity=".2"/><rect class="mz-grow" x="24" y="584" width="140" height="4" rx="2" fill="#fff"/>'
    b += "".join(
        f'<rect x="{24 + x}" y="578" width="2" height="16" fill="#fff" fill-opacity=".6"/>'
        for x in (62, 125, 187, 250)
    )
    b += t(24, 620, "01:12", 12, "#fff", mono=True, opacity=0.7) + t(
        336, 620, "04:30", 12, "#fff", mono=True, anchor="end", opacity=0.7
    )
    b += '<circle cx="180" cy="684" r="30" fill="#fff"/><path d="M172 670 v28 l22 -14 z" fill="#0e0e0e"/>'
    b += t(60, 689, "Take apart", 13, "#fff", anchor="middle", opacity=0.6) + t(
        300, 689, "Put back", 13, "#fff", anchor="middle", opacity=0.6
    )
    b += status_bar(dark=True)
    return screen(6, "The narrated instruction film, with captions and step markers", b, "#0e0e0e")


def replace() -> str:
    b = status_bar() + header("Replace a part")
    b += t(24, 106, "Which part do you need to change?", 15, MUTED)
    parts = ["A cover", "B screws", "C flex", "D battery", "E camera", "F port"]
    for i, name in enumerate(parts):
        x, y = 20 + (i % 2) * 164, 126 + (i // 2) * 96
        on = name.startswith("D")
        b += f'<rect x="{x}" y="{y}" width="156" height="84" rx="12" fill="{ORANGE if on else CARD}"/>'
        b += t(x + 16, y + 34, name[0], 22, "#fff" if on else INK, mono=True) + t(
            x + 16, y + 62, name[2:], 15, "#fff" if on else INK
        )
    plan = [
        ("Take apart to D", "steps 1–3"),
        ("Swap D for the new part", "your new battery"),
        ("Put back", "steps 3–1, 4 screws"),
    ]
    for i, (a, s) in enumerate(plan):
        y = 450 + i * 74
        b += (
            f'<g class="mz-in" style="--i:{i}"><circle cx="38" cy="{y - 5}" r="12" fill="{INK}"/>'
            + t(38, y, str(i + 1), 12, "#fff", mono=True, anchor="middle")
        )
        b += t(62, y, a, 18) + t(62, y + 22, s, 12, MUTED, mono=True) + "</g>"
    b += f'<rect x="20" y="676" width="320" height="50" rx="12" fill="{YELLOW}"/>' + t(
        180, 707, "Coming next", 15, INK, anchor="middle", weight=500
    )
    return screen(
        7, "Coming next: pick a part to replace and FixScribe plans the way to it and back", b
    )


SCREENS = [record, recognize, guide, reverse, check, live, film, replace]


def main() -> int:
    OUT.write_text("\n".join(draw() for draw in SCREENS) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
