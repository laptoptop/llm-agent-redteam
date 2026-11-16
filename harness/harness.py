#!/usr/bin/env python3
"""Agent red-team harness — v0.1.

Sends each attack module's payload at a live agent, records the tool-call trace, and
writes a report whose evidence is the trace itself (what the tool received, what it
returned), not an LLM's opinion about whether something bad happened.

usage:
  ./env/bin/python harness.py --model openai/qwen2.5-7b \
      --api-base http://localhost:8081/v1 --modules m01 m02 --out reports/run.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import report
from target import DVLAAgentTarget, TargetConfig
from modules.m01_override import ScopeOverride
from modules.m02_tao import TAOReplay

MODULES = {
    "m01": ScopeOverride,
    "m02": TAOReplay,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent red-team harness v0.1")
    ap.add_argument("--model", required=True, help="litellm model string, e.g. openai/qwen2.5-7b")
    ap.add_argument("--api-base", default="http://localhost:8081/v1")
    ap.add_argument("--modules", nargs="+", default=["m01", "m02"], choices=sorted(MODULES))
    ap.add_argument("--payload", default=None,
                    help="only run the payload with this id (e.g. p1-direct)")
    ap.add_argument("--dvla-repo", default=".", help="path to the DVLA checkout")
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--out", default="reports/latest.md")
    ap.add_argument("--json", default=None, help="also dump raw traces to this JSON file")
    args = ap.parse_args()

    for key in ("OPENAI_API_KEY",):
        if not __import__("os").getenv(key):
            print(f"warning: {key} not set; the target endpoint will reject requests",
                  file=sys.stderr)

    target = DVLAAgentTarget(TargetConfig(
        model=args.model, api_base=args.api_base,
        max_tokens=args.max_tokens, dvla_repo=args.dvla_repo,
    ))

    findings = []
    for key in args.modules:
        module = MODULES[key]()
        for payload_id, payload in module.payloads():
            if args.payload and payload_id != args.payload:
                continue
            print(f"[*] {module.name} / {payload_id} → {args.model}", flush=True)
            trace = target.run(module.name, payload)
            finding = module.judge(trace, payload_id)
            findings.append(finding)
            state = "VULNERABLE" if finding.vulnerable else "no finding"
            print(f"    {state}: {finding.impact}", flush=True)

    path = report.write(findings, f"{target.name} @ {args.api_base}", args.out)
    print(f"\nreport: {path}")

    if args.json:
        import json

        Path(args.json).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"traces: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
