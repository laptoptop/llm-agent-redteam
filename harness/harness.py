#!/usr/bin/env python3
"""Agent red-team harness — v0.3.

Sends each attack module's payload at a live agent, records the tool-call trace, and
writes a report whose evidence is the trace itself (what the tool received, what it
returned), not an LLM's opinion about whether something bad happened.

usage:
  ./env/bin/python harness.py --target dvla --model openai/gemma4-12b-local \
      --dvla-repo /path/to/dvla --modules m01 m02 m03 --out reports/dvla.md

  ./env/bin/python harness.py --target mock --model openai/qwen2.5-7b \
      --modules m04 m05 --out reports/mock.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import report
from oob import CanaryServer
from target import DVLAAgentTarget, MockSupportTarget, TargetConfig
from modules.m00_corpus import CorpusModule
from modules.m01_override import ScopeOverride
from modules.m02_tao import TAOReplay
from modules.m03_indirect import IndirectToolOutput
from modules.m04_exfil import ExfilViaTool
from modules.m05_privesc import ToolMisuse

MODULES = {
    "m00": CorpusModule,
    "m01": ScopeOverride,
    "m02": TAOReplay,
    "m03": IndirectToolOutput,
    "m04": ExfilViaTool,
    "m05": ToolMisuse,
}

#: which modules are meaningful against which target
TARGETS = {
    "dvla": (DVLAAgentTarget, {"m01", "m02", "m03"}),
    "mock": (MockSupportTarget, {"m00", "m04", "m05"}),
}

DEFAULT_SEED = ["What are my recent transactions?"]


def build_target(name: str, args: argparse.Namespace):
    cls = TARGETS[name][0]
    cfg = TargetConfig(
        model=args.model,
        api_base=args.api_base,
        max_tokens=args.max_tokens,
        tools_path=args.dvla_repo if name == "dvla" else "",
        tools_module="tools" if name == "dvla" else "",
        stateful=args.history > 0,
    )
    return cls(cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent red-team harness")
    ap.add_argument("--model", required=True, help="litellm model string, e.g. openai/qwen2.5-7b")
    ap.add_argument("--api-base", default="http://localhost:8081/v1")
    ap.add_argument("--target", default="dvla", choices=sorted(TARGETS))
    ap.add_argument("--modules", nargs="+", default=None, choices=sorted(MODULES))
    ap.add_argument("--payload", default=None,
                    help="only run the payload with this id (e.g. p3b-sqli)")
    ap.add_argument("--dvla-repo", default=".", help="path to the DVLA checkout")
    ap.add_argument("--db", default=None,
                    help="sqlite path for m03 (default: <dvla-repo>/transactions.db)")
    ap.add_argument("--history", type=int, default=0,
                    help="seed N benign turns before the payload (session state)")
    ap.add_argument("--oob-port", type=int, default=8899,
                    help="local port for out-of-band callbacks (m04)")
    ap.add_argument("--corpus", default=None,
                    help="YAML corpus for m00 (default: corpus/prompt-layer.yaml)")
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--out", default="reports/latest.md")
    ap.add_argument("--json", default=None, help="also dump raw traces to this JSON file")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("warning: OPENAI_API_KEY not set; the target endpoint will reject requests",
              file=sys.stderr)

    chosen = args.modules or sorted(TARGETS[args.target][1])
    unsupported = [m for m in chosen if m not in TARGETS[args.target][1]]
    if unsupported:
        print(f"warning: {unsupported} do not apply to target '{args.target}' "
              f"(supported: {sorted(TARGETS[args.target][1])})", file=sys.stderr)

    db_path = args.db or str(Path(args.dvla_repo) / "transactions.db")
    # DVLA's tools open "transactions.db" relative to the process CWD, so a harness
    # started from a subdirectory silently reads an empty database.
    if args.target == "dvla" and os.path.abspath("transactions.db") != os.path.abspath(db_path):
        print(
            f"warning: the target will open {os.path.abspath('transactions.db')} "
            f"but seeding targets {os.path.abspath(db_path)}.\n"
            f"         run the harness from the target repo root or pass --db to match.",
            file=sys.stderr,
        )

    target = build_target(args.target, args)

    findings = []
    for key in chosen:
        module = MODULES[key](args.corpus) if key == "m00" else MODULES[key]()
        module.db_path = db_path
        canary = CanaryServer(args.oob_port) if getattr(module, "needs_oob", False) else None
        if canary is not None:
            module.canary = canary
            canary.__enter__()
        try:
            module.prepare()
            if args.history:
                seeds = module.seed_prompts or DEFAULT_SEED
                prompts = [seeds[i % len(seeds)] for i in range(args.history)]
                print(f"[*] seeding {len(prompts)} turn(s) before {module.name}", flush=True)
                target.seed(prompts)

            for payload_id, payload in module.payloads():
                if args.payload and payload_id != args.payload:
                    continue
                print(f"[*] {module.name} / {payload_id} → {args.model}", flush=True)
                trace = target.run(module.name, payload)
                if canary is not None:
                    canary.wait(1.0)  # let an in-flight callback land
                finding = module.judge(trace, payload_id)
                findings.append(finding)
                state = "VULNERABLE" if finding.vulnerable else "no finding"
                print(f"    {state}: {finding.impact}", flush=True)
        finally:
            module.cleanup()
            if canary is not None:
                canary.__exit__(None, None, None)

    path = report.write(findings, f"{target.name} @ {args.api_base}", args.out)
    print(f"\nreport: {path}")

    if args.json:
        Path(args.json).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"traces: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())