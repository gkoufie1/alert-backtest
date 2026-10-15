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
                         parse_duration, relevant_faults, score_incident)
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
        targets = relevant_faults(rule, faults)
        ttds, missed = [], []
        print(f"\n{name}  (for: {rule.get('for', '0s')})")
        if not targets:
            print("  no incidents of the type(s) it is meant to detect in the library")

        for inc in targets:
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
            "detected": len(ttds),
            "incidents": len(targets),
            "missed": missed,
            "median_ttd_s": median_or_none(ttds),
            "false_fires": false_fires,
            "baseline_hours": round(baseline_hours, 3),
        })
    return summary, any_miss


def false_per_hour(s: dict) -> str:
    return f"{s['false_fires'] / s['baseline_hours']:.2f}" if s["baseline_hours"] else "n/a"


def render_table(summary: list[dict]) -> str:
    lines = ["| Rule | Detected | Median time to detect | False fires / hour |",
             "|---|---|---|---|"]
    lines += [f"| `{s['rule']}` | {s['detected']}/{s['incidents']} | {fmt_duration(s['median_ttd_s'])} "
              f"| {false_per_hour(s)} |" for s in summary]
    return "\n".join(lines) + "\n"


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
    p.add_argument("--json", help="also write the per-rule summary as JSON (read by tools/pr_comment.py)")
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

    report = render_table(summary)
    pathlib.Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.report).write_text(report)
    if args.json:
        pathlib.Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.json).write_text(json.dumps(
            {"faults": len(faults), "baselines": len(baselines), "rules": summary}, indent=2))
    print("\n" + report)
    return 1 if (args.fail_on_miss and any_miss) else 0


if __name__ == "__main__":
    sys.exit(main())
