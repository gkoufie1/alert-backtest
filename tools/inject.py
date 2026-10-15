"""Inject a fault into the sample app and record ground truth for the incident library.

Examples:
  python tools/inject.py --type errors  --magnitude 0.2 --duration 300
  python tools/inject.py --type latency --magnitude 800 --duration 300
  python tools/inject.py --type none    --duration 1800   # baseline: nothing broken
"""
import argparse
import json
import pathlib
import time
import uuid

import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--type", choices=["errors", "latency", "none"], required=True)
    p.add_argument("--magnitude", type=float, default=0.0,
                   help="error rate (0-1) for errors, added ms for latency")
    p.add_argument("--duration", type=int, default=300, help="seconds")
    p.add_argument("--app", default="http://localhost:8000")
    p.add_argument("--out", default="incidents")
    args = p.parse_args()

    incident_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{args.type}-{uuid.uuid4().hex[:4]}"
    out = pathlib.Path(args.out) / f"{incident_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    params = {}
    if args.type == "errors":
        params = {"error_rate": args.magnitude}
    elif args.type == "latency":
        params = {"latency_ms": args.magnitude}

    record = {"id": incident_id, "type": args.type, "params": params,
              "start": time.time(), "end": None, "status": "running"}
    if params:
        requests.post(f"{args.app}/chaos",
                      params={**params, "duration_s": args.duration}, timeout=5).raise_for_status()
    out.write_text(json.dumps(record, indent=2))
    print(f"[{incident_id}] started, running {args.duration}s (Ctrl-C ends it early)")

    try:
        deadline = record["start"] + args.duration
        while time.time() < deadline:
            time.sleep(min(30, deadline - time.time()))
            remaining = max(0, int(deadline - time.time()))
            if remaining:
                print(f"  ...{remaining}s remaining")
    except KeyboardInterrupt:
        print("  interrupted, ending incident now")
    finally:
        if params:
            requests.post(f"{args.app}/chaos/stop", timeout=5)
        record["end"] = time.time()
        record["status"] = "complete"
        out.write_text(json.dumps(record, indent=2))
        print(f"[{incident_id}] complete -> {out}")


if __name__ == "__main__":
    main()
