# alert-backtest

Backtest Prometheus alerting rules against recorded incidents before you merge them.

Teams tune alerts by gut feel and find out weeks later whether a change caused alert
fatigue or missed an outage. This project records real incident windows into a library
and replays proposed rules against them, reporting detection rate, time to detect, and
false fires per hour of normal traffic.

## Quickstart (local, ~15 minutes)

Requires Docker and Python 3.11+.

```bash
make up            # sample app + Prometheus + k6 load generator
make venv && source .venv/bin/activate
sleep 120          # let rate() windows fill with normal traffic

make baseline      # 30 min of normal traffic (run it in another terminal while you continue)
make errors        # 5 min at 20% error rate
make latency       # 5 min at +800ms latency

make backtest
make capture       # persist incident windows to Parquet
make replay        # same backtest from the Parquet library, no live Prometheus needed
```

Example output:

```
OrdersHighErrorRatio  (for: 2m)
  would have fired 2m30s after incident start   [20261014-101500-errors-3f2a, errors 20%]
  would have MISSED   [20261014-102100-latency-91bc, latency +800ms]
  0 false fire(s) across 0.5h of baseline traffic
```

Prometheus UI is at http://localhost:9090 and evaluates the same rules live, so you can
check the engine's predictions against what Prometheus actually did under *Alerts*.

## How it works

1. `tools/inject.py` toggles a fault in the app via `POST /chaos` and writes the
   incident's ground truth (type, start, end) to `incidents/<id>.json`.
2. `engine/backtest.py` evaluates each rule's `expr` at every evaluation tick across the
   incident window (a range query evaluates the expression as an instant query at each
   step, which mirrors the rule manager), then replays Prometheus' pending → firing
   state machine, including `for`, in `engine/core.py`.
3. A fault is *detected* if the alert starts firing between incident start and a grace
   period after it ends. Firing during `none` (baseline) windows counts as a false fire.
4. `tools/capture.py` saves raw samples around each incident to Parquet so the library
   outlives Prometheus retention.
5. `--source replay` (`make replay`) renders the Parquet library as OpenMetrics, backfills
   it with `promtool tsdb create-blocks-from openmetrics` into a throwaway
   `prom/prometheus` container (same version as compose), and runs the same queries there
   through the same `eval_ticks()` interface. The container is removed afterwards.
   Incidents without a Parquet capture are skipped.

## Known limitations (deliberate, for now)

- The default `--source prometheus` needs incidents within retention (30d); use
  `--source replay` for older ones. Replay only sees the metrics `tools/capture.py`
  captures (`METRICS`), so rules over other metrics need that list extended first.
- `keep_firing_for` and evaluation-time jitter are not modelled yet.
- `--step` must equal Prometheus' `evaluation_interval` (15s).

## Roadmap

- [x] Local loop: fault injection, ground truth, rule replay, scoring
- [x] Replay from the Parquet library (Prometheus-independent)
- [ ] GitHub Action: backtest changed rules on every PR and comment results
- [ ] Minikube + Chaos Mesh, MinIO as S3
- [ ] EKS + S3 + AWS FIS weekend run, with cost breakdown
