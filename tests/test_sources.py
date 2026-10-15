import json

import pandas as pd

from engine.sources import load_library, to_openmetrics


def frame(rows):
    return pd.DataFrame([{"metric": m, "labels": json.dumps(l, sort_keys=True),
                          "timestamp": float(t), "value": float(v)} for m, l, t, v in rows])


def test_to_openmetrics_groups_families_and_sorts_series():
    df = frame([
        ("http_requests_total", {"code": "500"}, 30, 2),
        ("http_requests_total", {"code": "200"}, 15, 1),
        ("http_request_duration_seconds_bucket", {"le": "0.5"}, 15, 7),
        ("http_requests_total", {"code": "500"}, 15, 1),
    ])
    assert to_openmetrics(df).splitlines() == [
        'http_request_duration_seconds_bucket{le="0.5"} 7.0 15.0',
        'http_requests_total{code="200"} 1.0 15.0',
        'http_requests_total{code="500"} 1.0 15.0',
        'http_requests_total{code="500"} 2.0 30.0',
        "# EOF",
    ]


def test_to_openmetrics_escapes_label_values():
    df = frame([("m", {"path": 'a"b\\c\nd'}, 1, 1)])
    assert to_openmetrics(df).splitlines()[0] == r'm{path="a\"b\\c\nd"} 1.0 1.0'


def test_to_openmetrics_without_labels():
    assert to_openmetrics(frame([("up", {}, 1, 1)])).splitlines()[0] == "up 1.0 1.0"


def test_load_library_drops_samples_captured_twice(tmp_path):
    a = frame([("m", {}, 1, 1), ("m", {}, 2, 2)])
    b = frame([("m", {}, 2, 2), ("m", {}, 3, 3)])
    a.to_parquet(tmp_path / "a.parquet", index=False)
    b.to_parquet(tmp_path / "b.parquet", index=False)
    assert sorted(load_library(str(tmp_path))["timestamp"]) == [1, 2, 3]
