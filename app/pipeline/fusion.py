"""Boundary fusion: snap Spark step times to voice and visual candidates."""

from dataclasses import dataclass, field
from pathlib import Path

from app import artifacts
from app.artifacts import ArtifactError
from app.config import Settings
from app.schemas import Analysis, Fusion, FusionStep, Scenes, Signals


class FusionError(Exception):
    """Raised when the fusion inputs cannot be read."""


SNAP_WINDOW_S = 1.5

_AGREEMENT = {"voice": 1.0, "pause": 0.8, "scene": 0.8, "spark": 0.6}


@dataclass
class _Candidate:
    kind: str  # "voice", "pause" or "scene"
    weight: float
    t: float | None = None  # point candidates
    start: float | None = None  # voice interval
    end: float | None = None
    used: bool = False
    used_t: float | None = None  # snapped time when first used
    used_by_end_of: int | None = field(default=None)  # step position whose end used it

    def snapped_time(self, spark_t: float) -> tuple[float, float]:
        """Return ``(snapped_t, |delta|)``: closest point of the candidate to ``spark_t``."""
        if self.start is not None and self.end is not None:
            lo, hi = (self.start, self.end) if self.start <= self.end else (self.end, self.start)
            snapped = min(max(spark_t, lo), hi)
            return snapped, abs(snapped - spark_t)
        assert self.t is not None
        return float(self.t), abs(float(self.t) - spark_t)


def collect_candidates(scenes: Scenes | None, signals: Signals | None) -> list[_Candidate]:
    """Build the weighted candidate pool from voice cuts and visual signals."""
    pool: list[_Candidate] = []
    if scenes is not None:
        intervals = list(scenes.cut_intervals)
        cuts = list(scenes.cuts)
        if intervals:
            for i, interval in enumerate(intervals):
                cut_t = float(cuts[i]) if i < len(cuts) else float(interval.start_s)
                pool.append(
                    _Candidate(
                        kind="voice",
                        weight=1.0,
                        t=cut_t,
                        start=float(interval.start_s),
                        end=float(interval.end_s),
                    )
                )
            # Cuts without a matching interval still count.
            for cut in cuts[len(intervals) :]:
                pool.append(_Candidate(kind="voice", weight=1.0, t=float(cut)))
        else:
            for cut in cuts:
                pool.append(_Candidate(kind="voice", weight=1.0, t=float(cut)))
    if signals is not None:
        for candidate in signals.candidates:
            if candidate.kind == "pause":
                weight = 0.6 * float(candidate.score)
            else:
                weight = 0.4 * float(candidate.score)
            pool.append(_Candidate(kind=candidate.kind, weight=weight, t=float(candidate.t)))
    return pool


def fuse(analysis: Analysis, scenes: Scenes | None, signals: Signals | None) -> Fusion:
    """Snap every Spark boundary to the best nearby candidate and score agreement."""
    pool = collect_candidates(scenes, signals)
    n_candidates = len(pool)
    has_candidates = n_candidates > 0

    sorted_steps = sorted(analysis.steps, key=lambda step: float(step.start_s))
    fusion_steps: list[FusionStep] = []
    prev_end: float | None = None
    orig_ends = [float(s.end_s) for s in sorted_steps]

    for pos, step in enumerate(sorted_steps):
        spark_start = float(step.start_s)
        spark_end = float(step.end_s)
        spark_conf = float(step.confidence)

        # --- start -------------------------------------------------------------
        start_t = spark_start
        start_source = "spark"
        # A candidate already used by the previous step's end may be shared when
        # the original boundaries were < 0.5 s apart.
        shared: _Candidate | None = None
        if pos > 0 and abs(spark_start - orig_ends[pos - 1]) < 0.5:
            for candidate in pool:
                if candidate.used and candidate.used_by_end_of == pos - 1:
                    shared = candidate
                    break

        start_choice: tuple[_Candidate, float, float] | None = None
        if shared is not None and shared.used_t is not None:
            snapped_shared = float(shared.used_t)
            if abs(snapped_shared - spark_start) <= SNAP_WINDOW_S:
                score_shared = shared.weight - 0.2 * abs(snapped_shared - spark_start)
                start_choice = (shared, snapped_shared, score_shared)
        if start_choice is None:
            # Evaluate all unused candidates, keeping only valid ones.
            best_valid: tuple[_Candidate, float, float] | None = None
            for candidate in pool:
                if candidate.used:
                    continue
                snapped, delta = candidate.snapped_time(spark_start)
                if delta > SNAP_WINDOW_S:
                    continue
                if prev_end is not None and snapped < prev_end:
                    continue
                if snapped >= spark_end:
                    continue
                score = candidate.weight - 0.2 * delta
                if best_valid is None or score > best_valid[2]:
                    best_valid = (candidate, snapped, score)
            start_choice = best_valid

        if start_choice is not None:
            candidate, snapped, _score = start_choice
            # Re-validate (the shared candidate was already used at the same time).
            if prev_end is None or snapped >= prev_end:
                if snapped < spark_end:
                    start_t = snapped
                    start_source = candidate.kind  # type: ignore[assignment]
                    if not candidate.used:
                        candidate.used = True
                        candidate.used_t = snapped
                    # If this start came from the shared end candidate, keep the
                    # original used mark; otherwise it is a normal use.

        # --- end ---------------------------------------------------------------
        end_t = spark_end
        end_source = "spark"
        best_end: tuple[_Candidate, float, float] | None = None
        for candidate in pool:
            if candidate.used:
                continue
            snapped, delta = candidate.snapped_time(spark_end)
            if delta > SNAP_WINDOW_S:
                continue
            if snapped <= start_t:
                continue
            score = candidate.weight - 0.2 * delta
            if best_end is None or score > best_end[2]:
                best_end = (candidate, snapped, score)
        if best_end is not None:
            candidate, snapped, _score = best_end
            end_t = snapped
            end_source = candidate.kind  # type: ignore[assignment]
            candidate.used = True
            candidate.used_t = snapped
            candidate.used_by_end_of = pos

        if not has_candidates:
            agreement = 1.0
        else:
            # The start is what a technician jumps to; the last step's end is usually the end
            # of the video with no evidence at all, so it must not lower every last step.
            agreement = _AGREEMENT[start_source]
        confidence = round(min(1.0, spark_conf * agreement), 3)
        fusion_steps.append(
            FusionStep(
                index=pos + 1,
                start_s=round(float(start_t), 4),
                end_s=round(float(end_t), 4),
                start_source=start_source,  # type: ignore[arg-type]
                end_source=end_source,  # type: ignore[arg-type]
                start_shift_s=round(float(start_t - spark_start), 4),
                end_shift_s=round(float(end_t - spark_end), 4),
                agreement=round(float(agreement), 4),
                confidence=float(confidence),
            )
        )
        prev_end = float(end_t)

    return Fusion(candidates=n_candidates, steps=fusion_steps)


def run(job_dir: Path, settings: Settings) -> Fusion:
    """Fuse Spark boundaries with voice/visual evidence; writes only ``fusion.json``."""
    del settings
    try:
        analysis = artifacts.load(job_dir, Analysis)
    except ArtifactError as exc:
        raise FusionError(str(exc)) from None
    try:
        scenes = artifacts.load_optional(job_dir, Scenes)
        signals = artifacts.load_optional(job_dir, Signals)
    except ArtifactError as exc:
        raise FusionError(str(exc)) from None
    result = fuse(analysis, scenes, signals)
    artifacts.save(job_dir, result)
    return result
