"""Where the engine gets evaluation results from.

PrometheusSource evaluates rules against the live Prometheus, which only works while
the incident windows are still within retention (30d in docker-compose).

ReplaySource loads the Parquet incident library into a throwaway Prometheus and
exposes the same eval_ticks() interface, so backtests no longer depend on retention.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import subprocess
import tempfile
import time

import requests

# Keep in step with docker-compose.yml so replay evaluates with the same PromQL engine.
PROMETHEUS_IMAGE = "prom/prometheus:v2.53.0"

REPLAY_CONFIG = "global:\n  evaluation_interval: 15s\n"


class PrometheusSource:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

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


def load_library(path: str):
    """Concatenate every incident's Parquet capture. Windows that overlap (a fault
    recorded during a baseline, say) were captured twice, so drop repeated samples."""
    import pandas as pd

    frames = [pd.read_parquet(p) for p in sorted(pathlib.Path(path).glob("*.parquet"))]
    if not frames:
        raise FileNotFoundError(f"no Parquet captures in {path}/; run tools/capture.py first")
    return pd.concat(frames).drop_duplicates(["metric", "labels", "timestamp"])


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def to_openmetrics(df) -> str:
    """Render captured samples as OpenMetrics text for `promtool tsdb create-blocks-from`.

    No # TYPE lines: every family is 'unknown', which keeps names such as
    http_requests_total and *_bucket exactly as captured. Families are contiguous
    and each series is in timestamp order, as the parser requires.
    """
    lines = []
    for (metric, labels), series in df.sort_values(["metric", "labels", "timestamp"]) \
                                      .groupby(["metric", "labels"], sort=False):
        label_text = ",".join(f'{k}="{_escape(str(v))}"' for k, v in json.loads(labels).items())
        name = f"{metric}{{{label_text}}}" if label_text else metric
        lines += [f"{name} {v!r} {ts!r}"
                  for ts, v in zip(series["timestamp"].tolist(), series["value"].tolist())]
    lines.append("# EOF")
    return "\n".join(lines) + "\n"


class ReplaySource:
    """Backfill the Parquet library into a throwaway Prometheus and query that.

    Use as a context manager; the container (and its anonymous volume) is removed
    on exit. Data goes in with `docker cp` rather than a bind mount, so no files
    owned by the container's user are left on the host.
    """

    def __init__(self, library: str = "incidents", image: str = PROMETHEUS_IMAGE,
                 ready_timeout: int = 180):
        self.library, self.image, self.ready_timeout = library, image, ready_timeout
        self.container = None
        self._prom: PrometheusSource | None = None

    def __enter__(self):
        om = to_openmetrics(load_library(self.library))
        script = ("promtool tsdb create-blocks-from openmetrics /etc/prometheus/replay.om /prometheus"
                  " && rm /etc/prometheus/replay.om"
                  " && exec prometheus --config.file=/etc/prometheus/replay.yml"
                  " --storage.tsdb.path=/prometheus --storage.tsdb.retention.time=100y")
        self.container = _docker("create", "-p", "127.0.0.1::9090", "--entrypoint", "sh",
                                 self.image, "-c", script)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for name, text in [("replay.om", om), ("replay.yml", REPLAY_CONFIG)]:
                    local = os.path.join(tmp, name)
                    pathlib.Path(local).write_text(text, newline="\n")
                    _docker("cp", local, f"{self.container}:/etc/prometheus/{name}")
            _docker("start", self.container)
            host_port = _docker("port", self.container, "9090/tcp").splitlines()[0].rsplit(":", 1)[1]
            self._prom = PrometheusSource(f"http://127.0.0.1:{host_port}")
            self._wait_ready()
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        if self.container:
            subprocess.run(["docker", "rm", "-f", "-v", self.container], capture_output=True)
            self.container = None
        return False

    def _wait_ready(self):
        deadline = time.time() + self.ready_timeout
        while time.time() < deadline:
            if _docker("inspect", "-f", "{{.State.Running}}", self.container) != "true":
                logs = subprocess.run(["docker", "logs", self.container],
                                      capture_output=True, text=True)
                raise RuntimeError(f"replay Prometheus exited:\n{logs.stdout}{logs.stderr}")
            try:
                if requests.get(f"{self._prom.url}/-/ready", timeout=2).ok:
                    return
            except requests.ConnectionError:
                pass
            time.sleep(1)
        raise TimeoutError(f"replay Prometheus not ready after {self.ready_timeout}s")

    def eval_ticks(self, expr: str, start: float, end: float, step: int):
        if self._prom is None:
            raise RuntimeError("use ReplaySource as a context manager")
        return self._prom.eval_ticks(expr, start, end, step)


def _docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()
