"""Pure backtesting logic. No I/O here, so it can be unit tested in isolation."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}


@dataclass(frozen=True)
class Interval:
    start: float
    end: float


@dataclass(frozen=True)
class Detection:
    detected: bool
    time_to_detect_s: float | None


def parse_duration(text: str | None) -> float:
    """Parse a Prometheus duration such as '2m', '1h30m' or '0s' into seconds."""
    if not text:
        return 0.0
    parts = re.findall(r"(\d+)(ms|s|m|h|d|w|y)", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"invalid Prometheus duration: {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in parts)


def firing_intervals(times: list[float], active: list[bool], for_s: float) -> list[Interval]:
    """Replay Prometheus' inactive -> pending -> firing state machine.

    times:  evaluation timestamps, ascending, one per evaluation_interval
    active: whether the alert expression returned any series at that tick
    for_s:  the rule's `for` duration; the alert fires once it has been
            continuously active for at least this long, and resets on the
            first tick where it is not active.
    """
    intervals: list[Interval] = []
    pending_since = firing_since = None
    for t, is_active in zip(times, active):
        if is_active:
            if pending_since is None:
                pending_since = t
            if firing_since is None and t - pending_since >= for_s:
                firing_since = t
        else:
            if firing_since is not None:
                intervals.append(Interval(firing_since, t))
            pending_since = firing_since = None
    if firing_since is not None and times:
        intervals.append(Interval(firing_since, times[-1]))
    return intervals


def score_incident(intervals: list[Interval], start: float, end: float, grace_s: float) -> Detection:
    """An incident counts as detected if the alert starts firing between its
    start and `grace_s` after its end."""
    for iv in intervals:
        if start <= iv.start <= end + grace_s:
            return Detection(True, iv.start - start)
    return Detection(False, None)


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None
