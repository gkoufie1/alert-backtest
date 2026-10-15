"""Capture raw metric samples around each recorded incident into Parquet.

This is the incident library: data that outlives Prometheus retention and that the
replay engine (week 2) will load into a throwaway Prometheus to backtest against.
"""
import argparse
import json
import pathlib

import pandas as pd
import requests

METRICS = ["http_requests_total", "http_request_duration_seconds_bucket"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prometheus", default="http://localhost:9090")
    p.add_argument("--incidents", default="incidents")
    p.add_argument("--pre", type=int, default=900, help="seconds captured before start")
    p.add_argument("--post", type=int, default=600, help="seconds captured after end")
    args = p.parse_args()

    selector = '{__name__=~"%s"}' % "|".join(METRICS)
    for meta_path in sorted(pathlib.Path(args.incidents).glob("*.json")):
        meta = json.loads(meta_path.read_text())
        parquet = meta_path.with_suffix(".parquet")
        if meta.get("status") != "complete" or parquet.exists():
            continue

        window_end = meta["end"] + args.post
        window = int(window_end - (meta["start"] - args.pre))
        r = requests.get(f"{args.prometheus}/api/v1/query",
                         params={"query": f"{selector}[{window}s]", "time": window_end}, timeout=60)
        r.raise_for_status()
        rows = []
        for series in r.json()["data"]["result"]:
            labels = dict(series["metric"])
            name = labels.pop("__name__")
            label_json = json.dumps(labels, sort_keys=True)
            for ts, value in series["values"]:
                rows.append({"metric": name, "labels": label_json,
                             "timestamp": float(ts), "value": float(value)})
        pd.DataFrame(rows).to_parquet(parquet, index=False)
        print(f"captured {len(rows):>6} samples -> {parquet}")


if __name__ == "__main__":
    main()
