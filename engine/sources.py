"""Where the engine gets evaluation results from.

Week 1: PrometheusSource evaluates rules against the live Prometheus, which still
holds the incident windows (retention is 30d in docker-compose).
Week 2: a ReplaySource will load the Parquet incident library into a throwaway
Prometheus and expose the same eval_ticks() interface, so nothing else changes.
"""
from __future__ import annotations

import math

import requests


class PrometheusSource:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def eval_ticks(self, expr: str, start: float, end: float, step: int):
        """Evaluate `expr` at every evaluation tick in [start, end].

        A range query evaluates the expression as an instant query at each step,
        which is what the rule manager does on every evaluation_interval. Alert
        expressions are filters, so a tick is 'active' when any series comes back.
        """
        start = math.floor(start / step) * step
        end = math.ceil(end / step) * step
        r = requests.get(f"{self.url}/api/v1/query_range",
                         params={"query": expr, "start": start, "end": end, "step": step},
                         timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("status") != "success":
            raise RuntimeError(f"query failed: {body}")
        hits = {round(float(ts), 3) for s in body["data"]["result"] for ts, _ in s["values"]}
        times = [start + i * step for i in range(int((end - start) // step) + 1)]
        return times, [round(t, 3) in hits for t in times]
