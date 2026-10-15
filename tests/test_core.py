import pytest

from engine.core import (Interval, firing_intervals, fmt_duration, parse_duration,
                         relevant_faults, score_incident)

STEP = 15


def ticks(pattern: str, start: float = 0.0):
    """'..###..' -> evaluation times and active flags, one char per 15s tick."""
    return [start + i * STEP for i in range(len(pattern))], [c == "#" for c in pattern]


@pytest.mark.parametrize("text,seconds", [
    ("0s", 0), ("30s", 30), ("2m", 120), ("1h30m", 5400), ("500ms", 0.5), (None, 0),
])
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("2 minutes")


def test_for_zero_fires_on_first_active_tick():
    times, active = ticks("..##..")
    assert firing_intervals(times, active, 0) == [Interval(30, 60)]


def test_for_duration_delays_firing():
    # active from t=15; with for=30s it fires at t=45, resets at t=90
    times, active = ticks(".#####.")
    assert firing_intervals(times, active, 30) == [Interval(45, 90)]


def test_flapping_resets_pending():
    # never active for 3 consecutive ticks, so a 30s `for` never fires
    times, active = ticks("##.##.##.")
    assert firing_intervals(times, active, 30) == []


def test_still_firing_at_window_end():
    times, active = ticks("..####")
    assert firing_intervals(times, active, 15) == [Interval(45, 75)]


def test_score_detected_and_ttd():
    result = score_incident([Interval(200, 400)], start=100, end=300, grace_s=60)
    assert result.detected and result.time_to_detect_s == 100


def test_fire_before_incident_is_not_a_detection():
    result = score_incident([Interval(50, 400)], start=100, end=300, grace_s=60)
    assert not result.detected


def test_fire_within_grace_counts():
    assert score_incident([Interval(350, 400)], 100, 300, 60).detected
    assert not score_incident([Interval(361, 400)], 100, 300, 60).detected


def test_fmt_duration():
    assert fmt_duration(220) == "3m40s"
    assert fmt_duration(45) == "45s"
    assert fmt_duration(None) == "-"


FAULTS = [{"id": "e", "type": "errors"}, {"id": "l", "type": "latency"}]


def test_rule_without_annotation_is_scored_against_every_fault():
    assert relevant_faults({"alert": "A"}, FAULTS) == FAULTS


def test_backtest_detects_filters_by_type():
    rule = {"alert": "A", "annotations": {"backtest_detects": "latency"}}
    assert [f["id"] for f in relevant_faults(rule, FAULTS)] == ["l"]
    rule["annotations"]["backtest_detects"] = "errors, latency"
    assert relevant_faults(rule, FAULTS) == FAULTS


def test_backtest_detects_rejects_typos():
    with pytest.raises(ValueError, match="laterncy"):
        relevant_faults({"alert": "A", "annotations": {"backtest_detects": "laterncy"}}, FAULTS)
