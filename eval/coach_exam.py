"""Exam for the live coach against an answer key written by eye (eval/coach_key.json).

python -m eval.coach_exam iphone --real          # spends credits, keeps Spark's and SAM's answers
python -m eval.coach_exam iphone --real --again  # reuses pointing and cutting: only the check runs
python -m eval.coach_exam iphone --real --walk   # the whole video in order, as a user would

A mark is right when its name is a part of the key and its cut-out fits that part. The coach was
tuned on the iphone video and on steps 9-17 of the ikea video, so only the other steps are held out.
"""

import json
import pickle
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from app import artifacts
from app.config import get_settings
from app.meta_client import make_client
from app.pipeline.live import LiveError, live_turn, marks_stages
from app.schemas import Guide

KEY = Path(__file__).with_name("coach_key.json")
CAP_USD = 1.5
MIN_FIT = 0.5
EVERY_S = 4.0


def fit(a, b) -> float:
    """Overlap of two boxes, from 0 to 1."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    shared = max(0, w) * max(0, h)
    whole = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared
    return shared / whole if whole > 0 else 0.0


def is_right(label: str, box: list[int], frame: dict) -> bool:
    """The name is in the key and the cut-out fits one of the boxes with that name."""
    words = label.lower()
    for name, boxes in frame.get("big", {}).items():
        if name in words and any(fit(box, b) >= MIN_FIT for b in boxes):
            return True
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for name, boxes in frame.get("small", {}).items():
        if name in words and any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes):
            return True
    return False


def draw(shot: Path, parts, frame: dict, target: Path) -> None:
    """The frame with the marks: green when the key says right, red when wrong."""
    image = cv2.imread(str(shot))
    height, width = image.shape[:2]
    for part in parts:
        color = (0, 200, 0) if is_right(part.label, part.box, frame) else (0, 0, 255)
        points = np.array([[x * width // 1000, y * height // 1000] for x, y in part.outline])
        cv2.polylines(image, [points], True, color, 3)
        x, y = points.min(axis=0)
        cv2.putText(image, part.label, (int(x), max(18, int(y) - 6)), 0, 0.7, color, 2)
    cv2.imwrite(str(target), image)


class Remembering:
    """The real client; pointing and cutting answers are kept, to try only a new check later."""

    def __init__(self, client, folder: Path, again: bool):
        self._client, self._folder, self._again = client, folder, again
        self.tag = ""
        self.calls = {}

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _remember(self, kind, call):
        turn = self.calls[self.tag, kind] = self.calls.get((self.tag, kind), 0) + 1
        path = self._folder / f"{self.tag}_{kind}{turn}.pkl"  # a second look keeps its own answer
        if self._again and path.is_file():
            return pickle.loads(path.read_bytes())
        answer = call()
        path.write_bytes(pickle.dumps(answer))
        return answer

    def respond(self, **kwargs):
        answer = self._client.respond(**kwargs)
        if kwargs.get("text", {}).get("format", {}).get("name") == "check":
            for tile in json.loads(answer.output_text)["tiles"]:
                if not tile["real"]:
                    print(f"   {self.tag} tile {tile['n']} no: {tile['why'][:150]}")
        return answer

    def ground(self, *args, **kwargs):
        return self._remember("ground", lambda: self._client.ground(*args, **kwargs))

    def segment_boxes(self, *args, **kwargs):
        return self._remember("cut", lambda: self._client.segment_boxes(*args, **kwargs))


def walk(source: Path, work: Path, settings, client, start: int = 1, end: int = 999) -> int:
    """The video in order, a frame every EVERY_S seconds, as a phone would send them.

    Two numbers: how many frames find the coach on the right step, and how many steps it reaches
    before they end. A coach is always a moment late, so the second one says if it keeps up.
    """
    guide = artifacts.load(work, Guide)
    current = start - 1
    pending = right = total = stood = 0
    reached = set()
    steps = [step for step in guide.steps if start <= step.index <= end]
    times = []
    t = steps[0].start_s
    while t < steps[-1].end_s:
        here = next((s for s in steps if s.start_s <= t < s.end_s), None)
        if here is None:  # between steps the guide says nothing: not scored
            t += EVERY_S
            continue
        shot = work / "walk.jpg"
        command = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}"]
        command += ["-i", str(source / "video.mp4"), "-frames:v", "1", "-q:v", "2", str(shot)]
        subprocess.run(command, check=True)
        started = time.monotonic()
        try:
            frame = shot.read_bytes()
            answer = live_turn(work, settings, frame, current, client, pending, stood)
        except LiveError as exc:
            print(here.index, "failed:", exc)
            break
        times.append(time.monotonic() - started)
        stood = stood + 1 if answer.step == current else 0
        current, pending = answer.step, answer.pending
        total += 1
        right += current == here.index
        if current == here.index:
            reached.add(here.index)
        mark = "ok" if current == here.index else "--"
        print(f"real {here.index:>2} {t:6.1f}s stands {current:>2} sees {answer.seen:>2} {mark}")
        t += EVERY_S
    median = sorted(times)[len(times) // 2] if times else 0
    print(f"frames on the right step: {right}/{total} = {right / max(1, total):.0%}")
    print(f"steps reached in time: {len(reached)}/{len(steps)} = {len(reached) / len(steps):.0%}")
    print(f"median {median:.1f}s, spent ${client.job_spend.total():.3f}")
    return 0


def main(argv: list[str]) -> int:
    real, again = "--real" in argv, "--again" in argv
    names = [a for a in argv if not a.startswith("--")]
    if not names or not real:
        print(__doc__)
        return 2
    exam = json.loads(KEY.read_text())[names[0]]
    source = Path("data/jobs") / exam["job"]
    work = Path("data/close_look") / f"exam_{names[0]}"
    memory = work / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(work / "live", ignore_errors=True)
    (work / "live").mkdir()
    shutil.copy(source / "guide.json", work / "guide.json")
    if not (work / "steps").exists():
        shutil.copytree(source / "steps", work / "steps")
    settings = replace(get_settings(), live_budget_usd=CAP_USD, live_max_calls=10000)
    real_client = make_client(replace(settings, job_budget_usd=CAP_USD), job_dir=work / "live")
    if "--walk" in argv:
        start = int(names[1]) if len(names) > 1 else 1
        end = int(names[2]) if len(names) > 2 else 999
        return walk(source, work, settings, real_client, start, end)
    client = Remembering(real_client, memory, again)
    shown = right = cut = cut_right = steps_right = steps_asked = targets = targets_hit = 0
    times = []
    for frame in exam["frames"]:
        n = frame["step"]
        if frame.get("ignore"):
            continue
        shot = work / f"frame_{n:02d}.jpg"
        command = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(frame["t_s"])]
        command += ["-i", str(source / "video.mp4"), "-frames:v", "1", "-q:v", "2", str(shot)]
        subprocess.run(command, check=True)
        image = shot.read_bytes()
        client.tag = f"{n:02d}"
        turn_path = memory / f"{n:02d}_turn.json"
        try:
            if again and turn_path.is_file():
                turn = json.loads(turn_path.read_text())
            else:
                answer = live_turn(work, settings, image, n - 1, client)
                turn = {"seen": answer.seen, "region": answer.object_box, "say": answer.say}
                turn_path.write_text(json.dumps(turn))
            started = time.monotonic()
            stages = list(marks_stages(work, settings, image, n, turn["region"], client))
        except LiveError as exc:
            print(n, "failed:", exc)
            continue
        times.append(time.monotonic() - started)
        steps_asked += 1
        steps_right += turn["seen"] == n
        final = stages[-1][1]
        draw(shot, final, frame, work / f"marks_{n:02d}.jpg")
        found = stages[0][1]
        cut += len(found)
        cut_right += sum(is_right(p.label, p.box, frame) for p in found)
        marks = [(p.label, is_right(p.label, p.box, frame)) for p in final]
        shown += len(marks)
        right += sum(ok for _, ok in marks)
        target = frame.get("target")
        if target:
            targets += 1
            targets_hit += any(ok and target in label.lower() for label, ok in marks)
        dropped = [p.label for p in found if p.label not in [m[0] for m in marks]]
        print(f"{n:>2} seen {turn['seen']:>2} {times[-1]:5.1f}s {marks} dropped {dropped}")
    median = sorted(times)[len(times) // 2] if times else 0
    print(f"steps right: {steps_right}/{steps_asked}")
    print(f"marks shown right: {right}/{shown} = {right / max(1, shown):.0%}")
    print(f"before the check: {cut_right}/{cut}")
    print(f"target part marked right: {targets_hit}/{targets}")
    print(f"median marks {median:.1f}s, spent ${real_client.job_spend.total():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
