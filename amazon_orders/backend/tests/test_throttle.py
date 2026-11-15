import random
import threading
from datetime import datetime, timedelta

import pytest

from amazon_orders_ha.throttle import (
    COOLDOWN_MAX,
    Cooldown,
    RequestGate,
    Stopped,
    backfill_window_open,
    get_preset,
    next_window_start,
)

from .conftest import FakeClock


def test_gate_spaces_requests_with_jitter_within_preset():
    clock = FakeClock()
    gate = RequestGate(clock, get_preset("careful"), random.Random(3))
    t0 = clock.monotonic()
    gate.wait()  # first request is immediate
    assert clock.monotonic() == t0
    gaps = []
    for _ in range(20):
        before = clock.monotonic()
        gate.wait()
        gaps.append(clock.monotonic() - before)
    assert all(20 <= g <= 40 + 1e-9 for g in gaps)
    assert len({round(g, 3) for g in gaps}) > 10  # jittered, not constant
    assert gate.requests == 21


def test_gate_counts_elapsed_time_already_spent():
    clock = FakeClock()
    gate = RequestGate(clock, get_preset("moderate"), random.Random(1))
    gate.wait()
    clock.advance(seconds=60)  # longer than any delay
    before = clock.monotonic()
    gate.wait()
    assert clock.monotonic() == before


def test_moderate_delay_range():
    clock = FakeClock()
    gate = RequestGate(clock, get_preset("moderate"), random.Random(5))
    gate.wait()
    for _ in range(10):
        before = clock.monotonic()
        gate.wait()
        assert 5 <= clock.monotonic() - before <= 10 + 1e-9


def test_gate_stops_promptly():
    clock = FakeClock()
    stop = threading.Event()
    gate = RequestGate(clock, get_preset("careful"), random.Random(1), stop)
    gate.wait()
    stop.set()
    with pytest.raises(Stopped):
        gate.wait()


def test_active_hours():
    careful, moderate = get_preset("careful"), get_preset("moderate")
    assert backfill_window_open(careful, datetime(2026, 1, 1, 1, 0))
    assert backfill_window_open(careful, datetime(2026, 1, 1, 5, 59))
    assert not backfill_window_open(careful, datetime(2026, 1, 1, 6, 0))
    assert not backfill_window_open(careful, datetime(2026, 1, 1, 0, 59))
    assert backfill_window_open(moderate, datetime(2026, 1, 1, 14, 0))
    assert next_window_start(careful, datetime(2026, 1, 1, 14, 0)) == datetime(2026, 1, 2, 1, 0)
    assert next_window_start(careful, datetime(2026, 1, 1, 0, 30)) == datetime(2026, 1, 1, 1, 0)
    assert next_window_start(moderate, datetime(2026, 1, 1, 14, 0)) is None


def test_cooldown_doubles_up_to_cap_and_resets():
    now = datetime(2026, 11, 15, 12, 0)
    cd = Cooldown(None)
    durs = [cd.trip(now, "429") for _ in range(7)]
    assert durs[:4] == [timedelta(minutes=15), timedelta(minutes=30), timedelta(minutes=60), timedelta(minutes=120)]
    assert durs[-1] == COOLDOWN_MAX == timedelta(hours=12)
    assert cd.active(now + timedelta(hours=11)) and not cd.active(now + timedelta(hours=12, seconds=1))
    cd.reset()
    assert not cd.active(now) and cd.trip(now, "x") == timedelta(minutes=15)
