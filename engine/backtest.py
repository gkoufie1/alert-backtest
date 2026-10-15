"""Backtest alert rules against recorded incidents.

  python -m engine.backtest --rules rules/alerts.yaml
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

from engine.core import (firing_intervals, fmt_duration, median_or_none,
                         parse_duration, score_incident)
from engine.sources import PrometheusSource, ReplaySource


def load_rules(path: str) -> list[dict]:
    doc = yaml.safe_load(pathlib.Path(path).read_text())
    return [r for g in doc.get("groups", []) for r in g.get("rules", []) if "alert" in r]


def load_incidents(path: str) -> list[dict]:
    items = [json.loads(p.read_text()) for p in sorted(pathlib.Path(path).glob("*.json"))]
    return [i for i in items if i.get("status") == "complete"]


def describe(inc: dict) -> str:
    if inc["type"] == "errors":
        return f"errors {inc['params']['error_rate']:.0%}"
    if inc["type"] == "latency":
        return f"latency +{inc['params']['latency_ms']:.0f}ms"
    return "baseline"


def backtest_rules(source, rules: list[dict], faults: list[dict], baselines: list[dict], args):
    summary, any_miss = [], False

    for rule in rules:
        name, for_s = rule["alert"], parse_duration(rule.get("for"))
        ttds, missed = [], []
        print(f"\n{name}  (for: {rule.get('for', '0s')})")

        for inc in faults:
            times, active = source.eval_ticks(rule["expr"], inc["start"] - args.pre,
                                              inc["end"] + args.grace, args.step)
            result = score_incident(firing_intervals(times, active, for_s),
                                    inc["start"], inc["end"], args.grace)
            if result.detected:
                ttds.append(result.time_to_detect_s)
                print(f"  would have fired {fmt_duration(result.time_to_detect_s)} after "
                      f"incident start   [{inc['id']}, {describe(inc)}]")
            else:
                missed.append(inc["id"])
                print(f"  would have MISSED   [{inc['id']}, {describe(inc)}]")

        false_fires, baseline_hours = 0, 0.0
        for inc in baselines:
            times, active = source.eval_ticks(rule["expr"], inc["start"], inc["end"], args.step)
            false_fires += len(firing_intervals(times, active, for_s))
            baseline_hours += (inc["end"] - inc["start"]) / 3600
        if baselines:
            print(f"  {false_fires} false fire(s) across {baseline_hours:.1f}h of baseline traffic")

        any_miss |= bool(missed)
        summary.append({
            "rule": name,
            "detected": f"{len(ttds)}/{len(faults)}",
            "median_ttd": fmt_duration(median_or_none(ttds)),
            "false_per_hour": f"{false_fires / baseline_hours:.2f}" if baseline_hours else "n/a",
        })
    return summary, any_miss


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rules", default="rules/alerts.yaml")
    p.add_argument("--incidents", default="incidents")
    p.add_argument("--prometheus", default="http://localhost:9090")
    p.add_argument("--source", choices=["prometheus", "replay"], default="prometheus",
                   help="live Prometheus, or replay the Parquet library in a throwaway one")
    p.add_argument("--step", type=int, default=15, help="must match evaluation_interval")
    p.add_argument("--pre", type=int, default=600, help="seconds evaluated before incident start")
    p.add_argument("--grace", type=int, default=300, help="seconds after end still counted as a detection")
    p.add_argument("--report", default="reports/backtest.md")
    p.add_argument("--fail-on-miss", action="store_true", help="exit 1 if any fault goes undetected (for CI)")
    args = p.parse_args()

    rules, incidents = load_rules(args.rules), load_incidents(args.incidents)
    if args.source == "replay":
        captured = [i for i in incidents
                    if (pathlib.Path(args.incidents) / f"{i['id']}.parquet").exists()]
        if len(captured) < len(incidents):
            print(f"Skipping {len(incidents) - len(captured)} incident(s) with no Parquet capture "
                  f"(run tools/capture.py).")
        incidents = captured
    faults = [i for i in incidents if i["type"] != "none"]
    baselines = [i for i in incidents if i["type"] == "none"]
    if not incidents:
        print("No completed incidents found. Run tools/inject.py first.")
        return 1

    source = (ReplaySource(args.incidents) if args.source == "replay"
              else PrometheusSource(args.prometheus))
    with source:
        summary, any_miss = backtest_rules(source, rules, faults, baselines, args)

    lines = ["| Rule | Detected | Median time to detect | False fires / hour |",
             "|---|---|---|---|"]
    lines += [f"| `{s['rule']}` | {s['detected']} | {s['median_ttd']} | {s['false_per_hour']} |"
              for s in summary]
    report = "\n".join(lines) + "\n"
    pathlib.Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.report).write_text(report)
    print("\n" + report)
    return 1 if (args.fail_on_miss and any_miss) else 0


if __name__ == "__main__":
    sys.exit(main())
