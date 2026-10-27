# ruff: noqa: E501 -- SVG markup reads better on one line per element
"""Draw the app screens shown in the landing's "What FixScribe does" section.

Run: ``python -m scripts.draw_screens`` -> writes web/templates/art/screens.html: one SVG phone
screen per feature, stacked; landing.js shows the one whose text is on screen. Each screen is a
faithful sketch of a real page of the app (record, progress, guide, reverse guide, check my step,
live coach, film) plus one marked "coming next" (replace a part).
"""

from pathlib import Path

from scripts.draw_mosaic import ORANGE, RED, YELLOW, gbox, ring

OUT = Path(__file__).resolve().parents[1] / "web" / "templates" / "art" / "screens.html"
W, H = 360, 760
INK = "#161616"
MUTED = "#6b6b6b"
SURFACE = "#f6f5f1"
CARD = "#ecebe5"
GREEN = "#1d7a3a"
FONT = "Inter Tight, Helvetica, Arial, sans-serif"
MONO = "JetBrains Mono, ui-monospace, Menlo, monospace"


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


def phone_mini(x, y, w=110, h=200, fill="#dfe4ee") -> str:
    """A small opened phone, used inside the screens' photos."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="#f4f6fb" stroke="{INK}" stroke-width="2"/>'
        f'<rect x="{x + 8}" y="{y + 8}" width="{w - 16}" height="{h - 16}" rx="12" fill="{fill}" stroke="{INK}" stroke-width="1.4"/>'
        f'<rect x="{x + 16}" y="{y + 16}" width="30" height="30" rx="7" fill="#f4f6fb" stroke="{INK}" stroke-width="1.4"/>'
        f'<rect x="{x + 18}" y="{y + 60}" width="{w - 36}" height="{h * 0.5:.0f}" rx="6" fill="#c7d1f6" stroke="{INK}" stroke-width="1.6"/>'
    )


def screen(i: int, label: str, body: str, bg=SURFACE) -> str:
    return (
        f'<svg class="screen" data-i="{i}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">'
        f'<rect width="{W}" height="{H}" fill="{bg}"/>{body}</svg>'
    )


# --- the screens ------------------------------------------------------------------------------


def record() -> str:
    b = status_bar(dark=True)
    b += '<rect x="0" y="48" width="360" height="560" fill="#2f5d50"/>'
    b += "".join(
        f'<path d="M{x} 48 V608" stroke="#fff" stroke-opacity=".08"/>' for x in range(30, 360, 30)
    )
    b += "".join(
        f'<path d="M0 {y} H360" stroke="#fff" stroke-opacity=".08"/>' for y in range(78, 608, 30)
    )
    b += phone_mini(120, 200, 120, 220)
    b += '<path d="M262 250 l60 -40" stroke="#e9c46a" stroke-width="10" stroke-linecap="round"/><path d="M250 258 l14 -9" stroke="#c9ced6" stroke-width="4" stroke-linecap="round"/>'
    b += (
        f'<g class="mz-glow"><rect x="24" y="66" width="92" height="28" rx="14" fill="{RED}"/></g>'
        + t(44, 85, "REC 00:42", 13, "#fff", mono=True)
    )
    b += t(
        180,
        580,
        "Say each step out loud — or stay silent.",
        14,
        "#fff",
        anchor="middle",
        opacity=0.85,
    )
    b += '<rect x="0" y="608" width="360" height="152" fill="#0e0e0e"/>'
    b += f'<circle cx="180" cy="680" r="36" fill="none" stroke="#fff" stroke-width="4"/><circle class="mz-glow" cx="180" cy="680" r="27" fill="{RED}"/>'
    b += t(60, 686, "Upload", 13, "#fff", opacity=0.7) + t(
        300, 686, "Flip", 13, "#fff", anchor="end", opacity=0.7
    )
    return screen(0, "Recording a repair video in FixScribe", b, "#0e0e0e")


def recognize() -> str:
    b = status_bar() + header("Making your guide")
    b += f'<rect x="20" y="96" width="320" height="150" rx="16" fill="{CARD}"/>'
    b += '<rect x="36" y="112" width="74" height="118" rx="10" fill="#1b2233"/>' + phone_mini(
        50, 124, 46, 94
    )
    b += t(126, 136, "Smartphone", 20, weight=500) + t(
        126, 158, "electronics · repair", 13, MUTED, mono=True
    )
    for i, chip in enumerate(("lithium battery", "glass")):
        x = 126 + i * 136
        b += (
            f'<rect x="{x}" y="176" width="{14 + len(chip) * 7.6:.0f}" height="24" rx="12" fill="none" stroke="#a35a00" stroke-opacity=".5"/>'
            + t(x + 8, 192, chip, 11.5, "#a35a00", mono=True)
        )
    b += t(126, 222, "Safety: caution · do-it-yourself allowed", 12, GREEN)
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
    b += '<rect x="20" y="122" width="320" height="260" rx="14" fill="#1b2233"/>' + phone_mini(
        118, 146, 124, 214
    )
    b += gbox(132, 202, 96, 116)
    for i, (x, y) in enumerate([(146, 340), (214, 340)], start=1):
        b += ring(x, y, i, r=8)
    b += (
        t(24, 414, "STEP 2", 12, MUTED, mono=True)
        + t(24, 444, "Remove the four screws", 22, weight=500)
        + t(24, 470, "at the bottom of the frame.", 22, weight=500)
    )
    b += (
        f'<rect x="24" y="490" width="312" height="52" rx="10" fill="{CARD}"/>'
        + t(38, 513, "“four little screws here”", 15)
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
    return screen(2, "A FixScribe guide step with its box, numbered screws, quote and proof", b)


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
        b += f'<g class="mz-slide" style="--i:{i}"><path d="M20 {y - 26} H340" stroke="{INK}" stroke-opacity=".12"/>'
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
    b = status_bar(dark=True)
    b += '<rect x="0" y="48" width="360" height="600" fill="#2b2b2b"/>' + phone_mini(
        90, 120, 180, 380
    )
    marks = [(118, 470, True), (242, 470, True), (118, 150, False), (242, 150, False)]
    for x, y, done in marks:
        if done:
            b += f'<circle cx="{x}" cy="{y}" r="14" fill="none" stroke="#7ee2a0" stroke-width="3.5"/><path d="M{x - 6} {y} l4 4 l8 -9" stroke="#7ee2a0" stroke-width="2.5" fill="none"/>'
        else:
            b += f'<g class="mz-glow"><circle cx="{x}" cy="{y}" r="14" fill="none" stroke="#ff8a80" stroke-width="3.5"/></g><circle cx="{x}" cy="{y}" r="5" fill="#d9dde3" stroke="{INK}" stroke-width="1.4"/>'
    b += t(24, 82, "Check this step · SAM 3.1", 13, "#fff", mono=True, opacity=0.8)
    b += f'<rect x="16" y="664" width="328" height="76" rx="14" fill="{INK}"/><circle cx="44" cy="702" r="7" fill="#ffb340"/>'
    b += t(62, 697, "Not yet", 16, "#fff", weight=500) + t(
        62, 718, "2 screws are still in place, at the top.", 13, "#fff", opacity=0.8
    )
    return screen(
        4, "Check my step: a photo of your own object, two screws still in place", b, "#0e0e0e"
    )


def live() -> str:
    b = ""
    b += '<rect x="0" y="0" width="360" height="760" fill="#24302b"/>' + phone_mini(
        104, 150, 152, 300
    )
    b += f'<g class="mz-lift"><rect x="126" y="236" width="108" height="150" rx="6" fill="#c7d1f6" stroke="{INK}" stroke-width="1.6"/></g>'
    b += (
        t(24, 82, "Live coach", 13, "#fff", mono=True, opacity=0.8)
        + '<circle class="mz-glow" cx="326" cy="77" r="6" fill="#30d158"/>'
    )
    b += '<rect x="14" y="520" width="332" height="216" rx="22" fill="#1c1c1e" fill-opacity=".86"/>'
    b += t(34, 556, "STEP 3 OF 5", 12, "#fff", mono=True, opacity=0.7) + t(
        326, 556, "ON TRACK", 12, "#30d158", mono=True, anchor="end"
    )
    b += t(34, 596, "Lift the battery", 24, "#fff", weight=500) + t(
        34, 626, "with the pull tabs.", 24, "#fff", weight=500
    )
    b += t(34, 662, "Next: disconnect the flex cable", 14, "#fff", opacity=0.7)
    for i in range(14):
        h = 6 + (abs(((i * 29) % 13) - 6)) * 2.4
        b += f'<rect class="mz-glow" x="{34 + i * 7}" y="{700 - h / 2:.1f}" width="3" height="{h:.1f}" rx="1.5" fill="#fff" style="animation-delay:{i * 0.09:.2f}s"/>'
    b += t(150, 704, "speaking", 12, "#fff", mono=True, opacity=0.6)
    return screen(
        5,
        "Live coach: the camera sees your work and says which step you are on and what comes next",
        b,
        "#24302b",
    )


def film() -> str:
    b = ""
    b += (
        '<rect x="0" y="0" width="360" height="760" fill="#0e0e0e"/>'
        + '<rect x="0" y="120" width="360" height="420" fill="#1b2233"/>'
        + phone_mini(110, 150, 140, 260)
    )
    b += gbox(126, 226, 108, 124)
    b += t(24, 82, "Replace the battery · film", 13, "#fff", mono=True, opacity=0.8)
    b += (
        '<rect x="20" y="470" width="320" height="56" rx="10" fill="#000" fill-opacity=".72"/>'
        + t(180, 504, "Unscrew the four screws at the bottom.", 14, "#fff", anchor="middle")
    )
    b += '<rect x="24" y="584" width="312" height="4" rx="2" fill="#fff" fill-opacity=".2"/><rect class="mz-grow" x="24" y="584" width="140" height="4" rx="2" fill="#fff"/>'
    b += "".join(
        f'<rect x="{24 + x}" y="578" width="2" height="16" fill="#fff" fill-opacity=".6"/>'
        for x in (62, 125, 187, 250)
    )
    b += t(24, 620, "01:12", 12, "#fff", mono=True, opacity=0.7) + t(
        336, 620, "04:30", 12, "#fff", mono=True, anchor="end", opacity=0.7
    )
    b += '<circle cx="180" cy="680" r="30" fill="#fff"/><path d="M172 666 v28 l22 -14 z" fill="#0e0e0e"/>'
    b += t(60, 686, "Take apart", 13, "#fff", opacity=0.6) + t(
        300, 686, "Put back", 13, "#fff", anchor="end", opacity=0.6
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
        fill = ORANGE if on else CARD
        b += f'<rect x="{x}" y="{y}" width="156" height="84" rx="12" fill="{fill}"/>'
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
            f'<g class="mz-slide" style="--i:{i}"><circle cx="38" cy="{y - 5}" r="12" fill="{INK}"/>'
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
