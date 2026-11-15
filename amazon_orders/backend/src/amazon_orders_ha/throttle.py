"""Request gate, active hours and backoff/cooldown logic (SPEC §5). Clock-injectable."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dtime
from typing import Any, Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Wall clock whose sleep can be interrupted through ``stop``."""

    def __init__(self, stop: threading.Event | None = None):
        self.stop = stop or threading.Event()

    def now(self) -> datetime:
        return datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        self.stop.wait(seconds)


class Stopped(Exception):
    """Raised when the engine is asked to stop while waiting."""


@dataclass(frozen=True)
class Preset:
    name: str
    delay_min: float
    delay_max: float
    backfill_hours: tuple[int, int] | None  # [start, end) local hours; None = any time


PRESETS = {
    "careful": Preset("careful", 20, 40, (1, 6)),
    "moderate": Preset("moderate", 5, 10, None),
}


def get_preset(name: str) -> Preset:
    return PRESETS.get(name, PRESETS["careful"])


def backfill_window_open(preset: Preset, now: datetime) -> bool:
    if preset.backfill_hours is None:
        return True
    start, end = preset.backfill_hours
    return start <= now.hour < end


def next_window_start(preset: Preset, now: datetime) -> datetime | None:
    if preset.backfill_hours is None or backfill_window_open(preset, now):
        return None
    start = preset.backfill_hours[0]
    cand = datetime.combine(now.date(), dtime(start))
    return cand if cand > now else cand + timedelta(days=1)


class RequestGate:
    """Spaces every Amazon request by a random jitter. Single consumer, never parallel."""

    def __init__(
        self,
        clock: Clock,
        preset: Preset,
        rng: random.Random | None = None,
        stop: threading.Event | None = None,
    ):
        self.clock = clock
        self.preset = preset
        self.rng = rng or random.Random()
        self.stop = stop
        self._last: float | None = None
        self.requests = 0

    def wait(self) -> float:
        """Block until the next request may be sent. Returns seconds slept."""
        slept = 0.0
        if self._last is not None:
            delay = self.rng.uniform(self.preset.delay_min, self.preset.delay_max)
            remaining = delay - (self.clock.monotonic() - self._last)
            if remaining > 0:
                self._sleep(remaining)
                slept = remaining
        if self.stop is not None and self.stop.is_set():
            raise Stopped()
        self._last = self.clock.monotonic()
        self.requests += 1
        return slept

    def _sleep(self, seconds: float) -> None:
        # Sleep in slices so a stop request is honoured quickly.
        left = seconds
        while left > 0:
            if self.stop is not None and self.stop.is_set():
                raise Stopped()
            step = min(left, 1.0)
            self.clock.sleep(step)
            left -= step


COOLDOWN_BASE = timedelta(minutes=15)
COOLDOWN_MAX = timedelta(hours=12)


class Cooldown:
    """Exponential cooldown persisted in ``sync_state['cooldown']`` (15 min doubling up to 12 h)."""

    def __init__(self, data: dict[str, Any] | None):
        self.data = dict(data or {})

    @property
    def level(self) -> int:
        return int(self.data.get("level", 0))

    def until(self) -> datetime | None:
        u = self.data.get("until")
        return datetime.fromisoformat(u) if u else None

    def active(self, now: datetime) -> bool:
        u = self.until()
        return bool(u and u > now)

    def trip(self, now: datetime, reason: str) -> timedelta:
        dur = min(COOLDOWN_BASE * (2 ** self.level), COOLDOWN_MAX)
        self.data = {
            "until": (now + dur).replace(microsecond=0).isoformat(),
            "level": self.level + 1,
            "reason": reason,
            "since": now.replace(microsecond=0).isoformat(),
        }
        return dur

    def reset(self) -> None:
        self.data = {}
