"""Tap a fastener: the user fixes the fastener map of one step by hand.

A tap where a fastener is missing sends that exact point to SAM 3.1 video, which follows it
through the step clip (the same zoomed clip the perception stage used), so it gets its exact
outline on every frame and a number in the ledger. A tap on a wrong marker removes it, with no
Meta call. Either way the step's overlay, the ledger and the guide are rebuilt. Taps that call
SAM are capped per job so a page left open cannot eat the budget.
"""

import shutil
from pathlib import Path
from typing import Any

import numpy as np

from app import artifacts
from app.config import Settings
from app.meta_client import make_client
from app.pipeline import publish
from app.pipeline.fasteners import (
    Found,
    cut_step_clip,
    cut_zoom,
    follow,
    load_found,
    read_window,
    reading_order,
    save_found,
    work_area,
)
from app.pipeline.perception import best_video, fill_ledger, make_overlay
from app.schemas import IngestInfo, Perception, Plan, Step

MAX_TAPS = 30
TAP_SIDE = 0.03  # the tapped fastener's area: this share of the frame around the point


class TapError(Exception):
    """A user-facing reason the tap could not be applied."""


def _taps_path(job_dir: Path) -> Path:
    return job_dir / "taps.txt"


def taps_used(job_dir: Path) -> int:
    try:
        return int(_taps_path(job_dir).read_text(encoding="utf-8").strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def _load(job_dir: Path, index: int) -> tuple[Plan, Step, Found, Perception]:
    plan = artifacts.load(job_dir, Plan)
    step = next((item for item in plan.steps if item.index == index), None)
    if step is None or not (step.screws and step.screws.count):
        raise TapError(f"step {index} has no fasteners to mark")
    found = load_found(job_dir, index)
    if found is None:
        raise TapError("this step was not analysed for fasteners yet")
    perception = artifacts.load(job_dir, Perception)
    return plan, step, found, perception


def _rebuild(job_dir: Path, settings: Settings, plan: Plan, perception: Perception) -> Perception:
    """Renumber every step's ledger S1, S2... in step order, redraw overlays, republish."""
    next_number = 1
    steps = {step.index: step for step in plan.steps}
    for sp in perception.steps:
        found = load_found(job_dir, sp.index)
        if found is not None and sp.index in steps:
            next_number = fill_ledger(sp, found, next_number)
        else:
            for record in sp.removed:
                record.id = f"S{next_number}"
                next_number += 1
    artifacts.save(job_dir, perception)
    publish.run(job_dir, settings)
    return perception


def _seed_frame(
    job_dir: Path, plan: Plan, step: Step, found: Found, work: Path
) -> tuple[Path, np.ndarray]:
    """Cut the step clip again exactly as perception did; return it and the drawn frame."""
    video, prefilter = best_video(job_dir, artifacts.load_optional(job_dir, IngestInfo))
    end_s = min(step.end_s, plan.duration_s) if plan.duration_s else step.end_s
    clip = work / "clip.mp4"
    cut_step_clip(video, step.start_s, end_s, found.fps, clip, prefilter)
    frame = read_window(clip, found.seed, found.seed + 1).get(found.seed)
    if frame is None:
        raise TapError("could not read the step's frame")
    return clip, frame


def add_fastener(
    job_dir: Path, settings: Settings, index: int, x: float, y: float, client: Any = None
) -> Perception:
    """SAM follows the fastener at (x, y) (0..1 of the step's fastener image) and adds it."""
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise TapError("the tap is outside the image")
    if taps_used(job_dir) >= MAX_TAPS:
        raise TapError(f"tap limit reached for this job ({MAX_TAPS} taps)")
    plan, step, found, perception = _load(job_dir, index)
    width, height = found.size
    px, py = x * width, y * height
    work = job_dir / "steps" / f"{index:02d}_tap"
    work.mkdir(parents=True, exist_ok=True)
    try:
        clip, frame = _seed_frame(job_dir, plan, step, found, work)
        half = TAP_SIDE * max(width, height) / 2
        area = work_area([(px - half, py - half, px + half, py + half)], width, height)
        scale = cut_zoom(clip, area, work / "zoom.mp4")
        artifacts.write_text_atomic(_taps_path(job_dir), str(taps_used(job_dir) + 1))
        if client is None:
            client = make_client(settings, job_dir=job_dir)
        tracks = follow(
            client, work / "zoom.mp4", found.size, [(found.seed, (px, py))], area, scale
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    new = max((oid for boxes in found.frames.values() for oid in boxes), default=0) + 1
    seen = tracks.get(found.seed, {}).get(1)
    if seen is None:
        raise TapError("SAM found nothing to follow there; tap the centre of the fastener")
    for index_, boxes in tracks.items():
        if 1 in boxes:
            found.frames.setdefault(index_, {})[new] = boxes[1]
    found.kept = reading_order(
        {oid: found.frames[found.seed][oid] for oid in [*found.kept, new]}, height
    )
    found.confidence[new] = 1.0  # a person pointed at it
    save_found(job_dir, index, found)
    sp = next(item for item in perception.steps if item.index == index)
    sp.notes = [note for note in sp.notes if "clearly visible" not in note]
    sp.notes.append("Fastener map corrected by hand.")
    perception = _rebuild(job_dir, settings, plan, perception)
    sp = next(item for item in perception.steps if item.index == index)
    sp.overlay = make_overlay(job_dir, step, frame, sp)
    artifacts.save(job_dir, perception)
    return perception


def remove_fastener(job_dir: Path, settings: Settings, index: int, number: int) -> Perception:
    """Drop marker ``number`` of the step (no Meta call)."""
    plan, step, found, perception = _load(job_dir, index)
    sp = next((item for item in perception.steps if item.index == index), None)
    if sp is None or not 1 <= number <= len(sp.removed):
        raise TapError(f"step {index} has no marker {number}")
    visible = [oid for oid in found.kept if oid in found.frames.get(found.seed, {})]
    found.kept = [oid for oid in found.kept if oid != visible[number - 1]]
    save_found(job_dir, index, found)
    sp.notes = [note for note in sp.notes if "clearly visible" not in note]
    sp.notes.append("Fastener map corrected by hand.")
    perception = _rebuild(job_dir, settings, plan, perception)
    work = job_dir / "steps" / f"{index:02d}_tap"
    work.mkdir(parents=True, exist_ok=True)
    try:
        _, frame = _seed_frame(job_dir, plan, step, found, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sp = next(item for item in perception.steps if item.index == index)
    sp.overlay = make_overlay(job_dir, step, frame, sp)
    artifacts.save(job_dir, perception)
    return perception
