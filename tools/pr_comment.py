"""Render the PR comment: backtest results for the PR's rules, compared with the base branch.

  python -m tools.pr_comment --head head.json [--base base.json] > comment.md

Cells show `base → head` only where the PR changes a result.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from engine.backtest import false_per_hour
from engine.core import fmt_duration

MARKER = "<!-- alert-backtest -->"


def cells(s: dict) -> tuple[str, str, str]:
    return (f"{s['detected']}/{s['incidents']}", fmt_duration(s["median_ttd_s"]), false_per_hour(s))


def render(head: dict, base: dict | None, library: str) -> str:
    base_rules = {s["rule"]: s for s in (base or {}).get("rules", [])}
    head_names = {s["rule"] for s in head["rules"]}
    missed = [(s["rule"], i) for s in head["rules"] for i in s["missed"]]
    baseline_h = max((s["baseline_hours"] for s in head["rules"]), default=0)

    status = (f"**{len(missed)} missed detection(s)**" if missed
              else "Every rule caught every incident it is meant to detect.")
    lines = [MARKER, "### Alert backtest", "",
             f"{status} Replayed against {head['faults']} fault incident(s) and "
             f"{baseline_h:.1f}h of baseline traffic from `{library}`.", "",
             "| Rule | Detected | Median time to detect | False fires / hour |",
             "|---|---|---|---|"]
    for s in head["rules"]:
        now = cells(s)
        if s["rule"] not in base_rules:
            row = list(now)
            name = f"`{s['rule']}` (new)" if base is not None else f"`{s['rule']}`"
        else:
            before = cells(base_rules[s["rule"]])
            row = [n if b == n else f"{b} → **{n}**" for b, n in zip(before, now)]
            name = f"`{s['rule']}`"
        lines.append(f"| {name} | " + " | ".join(row) + " |")
    for name in base_rules.keys() - head_names:
        lines.append(f"| ~~`{name}`~~ (removed) | | | |")

    if missed:
        lines += ["", "Missed:"] + [f"- `{rule}`: {inc}" for rule, inc in missed]
    if base is not None:
        lines += ["", "_`base → head` where this PR changes a result; both use this PR's engine._"]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--head", required=True)
    p.add_argument("--base", help="omit, or point at a missing file, when the base has no rules")
    p.add_argument("--library", default="examples/incidents")
    args = p.parse_args()
    head = json.loads(pathlib.Path(args.head).read_text())
    base_path = pathlib.Path(args.base) if args.base else None
    base = json.loads(base_path.read_text()) if base_path and base_path.exists() else None
    sys.stdout.reconfigure(encoding="utf-8")  # the arrows, on consoles that default to cp1252
    print(render(head, base, args.library), end="")


if __name__ == "__main__":
    main()
