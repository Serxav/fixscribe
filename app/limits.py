"""Per-visitor limits, so one person cannot use up the Meta credits meant for every visitor.

There are no accounts, so a visitor is their IP address. The counters live in memory: a restart
clears them, and the spend counters in meta_client.py stay the hard ceiling behind them.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Depends, Request

from app.config import Settings

DAY_S = 24 * 3600
HOUR_S = 3600
COACH_CALLS_PER_MINUTE = 40  # the page sends at most one frame every 2.5 s, plus the marks


class LimitReached(Exception):
    """A visitor used up one of their limits; the message says which and when it comes back."""


@dataclass
class _Window:
    limit: int
    seconds: float


class Limiter:
    """Counts each visitor's actions in sliding windows, thread-safe."""

    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._minutes: dict[str, dict[int, None]] = {}  # coach minutes used, per visitor

    def _claim(self, who: str, kind: str, window: _Window, now: float) -> bool:
        events = self._events.setdefault((who, kind), deque())
        while events and now - events[0] >= window.seconds:
            events.popleft()
        if len(events) >= window.limit:
            return False
        events.append(now)
        return True

    def claim(self, who: str, kind: str, settings: Settings) -> None:
        """Count one action, or raise LimitReached without counting it."""
        now = self._clock()
        with self._lock:
            if kind == "video":
                window, sentence = (
                    _Window(settings.visitor_videos_per_day, DAY_S),
                    (
                        f"You can turn {settings.visitor_videos_per_day} videos into guides a day. "
                        "Try again tomorrow."
                    ),
                )
            elif kind == "question":
                window, sentence = (
                    _Window(settings.visitor_questions_per_hour, HOUR_S),
                    (
                        f"You can ask {settings.visitor_questions_per_hour} questions an hour. "
                        "Try again later."
                    ),
                )
            elif kind == "action":
                window, sentence = (
                    _Window(settings.visitor_actions_per_hour, HOUR_S),
                    (
                        f"You can use {settings.visitor_actions_per_hour} AI actions an hour. "
                        "Try again later."
                    ),
                )
            elif kind == "coach":
                self._coach(who, now, settings)
                return
            else:
                raise ValueError(f"unknown limit {kind!r}")
            if window.limit > 0 and not self._claim(who, kind, window, now):
                raise LimitReached(sentence)

    def _coach(self, who: str, now: float, settings: Settings) -> None:
        """The live coach is limited in minutes a day, and in calls a minute against scripts."""
        allowed = settings.visitor_coach_minutes_per_day
        if allowed <= 0:
            return
        minute = int(now // 60)
        used = self._minutes.setdefault(who, {})
        for old in [m for m in used if minute - m >= DAY_S // 60]:
            del used[old]
        if minute not in used and len(used) >= allowed:
            raise LimitReached(
                f"The live coach is limited to {allowed} minutes a day. Try again tomorrow."
            )
        if not self._claim(who, "coach-burst", _Window(COACH_CALLS_PER_MINUTE, 60), now):
            raise LimitReached("Too many frames at once. Wait a moment.")
        used[minute] = None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._minutes.clear()


LIMITER = Limiter()


def visitor(request: Request, settings: Settings) -> str:
    """Who is asking. Behind a proxy: its own, last entry of X-Forwarded-For (the rest is faked)."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def limit(kind: str):
    """A route dependency that counts one ``kind`` action for the visitor, or refuses it."""
    from app.routes.upload import settings_dep  # here: the upload routes use limit() themselves

    def check(request: Request, settings: Settings = Depends(settings_dep)) -> None:  # noqa: B008
        LIMITER.claim(visitor(request, settings), kind, settings)

    return check
