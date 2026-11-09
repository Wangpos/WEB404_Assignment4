#!/usr/bin/env python3
"""Pretty-print the last N ModSecurity audit-log entries (JSON format).

Usage:  python3 tools/waf_log.py [-n 3]
Shows, for each transaction: time, method, URI, status and every rule that
matched (rule id + message + matched data).
"""
import argparse
import json
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "waf" / "logs" / "audit.log"

ap = argparse.ArgumentParser()
ap.add_argument("-n", type=int, default=1, help="number of entries to show")
args = ap.parse_args()

lines = [l for l in LOG.read_text(errors="replace").splitlines() if l.startswith("{")]
for line in lines[-args.n:]:
    t = json.loads(line)["transaction"]
    req, status = t["request"], t["response"].get("http_code")
    print(f"[{t['time_stamp']}] {req['method']} {req['uri']}  ->  HTTP {status}"
          f"  (interrupted: {t.get('is_interrupted')})")
    for m in t.get("messages", []):
        d = m["details"]
        print(f"   rule {d['ruleId']:>7}  {m['message']}")
        if d.get("data"):
            print(f"                 data: {d['data'][:110]}")
    print()
