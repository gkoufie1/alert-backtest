"""Generate the sample incident library in examples/incidents/ (used by CI and `make demo`).

It mimics what tools/inject.py + tools/capture.py record from the sample app: 10 req/s
scraped every 15s, 5-30ms latency, the app's histogram buckets and the scrape's job and
instance labels. Seeded and pinned to fixed dates, so it regenerates byte for byte.
Replace it with real captures whenever you have them.

  python tools/synth_library.py [--out examples/incidents]
"""
import argparse
import json
import pathlib
import random

import pandas as pd

STEP, RPS = 15, 10
BUCKETS = ["0.01", "0.025", "0.05", "0.1", "0.25", "0.5", "1.0", "2.5", "5.0", "+Inf"]
BASE = {"route": "/api/orders", "job": "orders", "instance": "app:8000"}
EPOCH = 1756684800  # 2026-09-01T00:00:00Z
PRE, POST = 900, 600  # tools/capture.py defaults

# (id suffix, type, params, start offset, duration, blips: (offset into window, seconds, error rate))
INCIDENTS = [
    ("errors-20pct", "errors", {"error_rate": 0.2}, 0, 300, []),
    ("errors-8pct", "errors", {"error_rate": 0.08}, 2 * 3600, 300, []),
    ("latency-800ms", "latency", {"latency_ms": 800.0}, 4 * 3600, 300, []),
    ("latency-600ms", "latency", {"latency_ms": 600.0}, 6 * 3600, 300, []),
    # an hour of normal traffic with a 60s deploy hiccup: a rule without a long enough
    # `for` pages on it, which is what false-fire scoring is there to catch
    ("baseline", "none", {}, 8 * 3600, 3600, [(1800, 60, 0.15)]),
]


def simulate(rng, kind, params, start, duration, blips):
    counts = {"200": 0.0, "500": None}  # the 500 series only exists after the first error
    buckets = dict.fromkeys(BUCKETS, 0.0)
    rows = []
    for t in range(start - PRE, start + duration + POST + 1, STEP):
        faulty = start < t <= start + duration  # a scrape reports the 15s before it
        error_rate = params.get("error_rate", 0.0) if faulty else 0.0
        error_rate = max([error_rate] + [r for off, secs, r in blips
                                         if start + off <= t < start + off + secs])
        extra = params.get("latency_ms", 0.0) / 1000 if faulty else 0.0
        for _ in range(int(rng.gauss(RPS * STEP, 6))):
            code = "500" if rng.random() < error_rate else "200"
            counts[code] = (counts[code] or 0.0) + 1
            seconds = rng.uniform(0.005, 0.03) + extra
            for b in BUCKETS:
                if b == "+Inf" or seconds <= float(b):
                    buckets[b] += 1
        for code, value in counts.items():
            if value is not None:
                rows.append(("http_requests_total", {**BASE, "code": code}, t, value))
        for le, value in buckets.items():
            rows.append(("http_request_duration_seconds_bucket",
                         {**BASE, "le": le}, t, value))
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="examples/incidents")
    args = p.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)

    for suffix, kind, params, offset, duration, blips in INCIDENTS:
        start = EPOCH + offset
        incident_id = f"20260901-{offset // 3600:02d}0000-{suffix}"
        rows = simulate(rng, kind, params, start, duration, blips)
        pd.DataFrame([{"metric": m, "labels": json.dumps(l, sort_keys=True),
                       "timestamp": float(t), "value": float(v)} for m, l, t, v in rows]) \
            .to_parquet(out / f"{incident_id}.parquet", index=False)
        # inject.py records wall-clock times, which never line up with scrapes
        meta = {"id": incident_id, "type": kind, "params": params, "start": start + 4.2,
                "end": start + duration + 4.2, "status": "complete", "synthetic": True}
        (out / f"{incident_id}.json").write_text(json.dumps(meta, indent=2) + "\n", newline="\n")
        print(f"{len(rows):>6} samples -> {out / incident_id}.parquet")


if __name__ == "__main__":
    main()
