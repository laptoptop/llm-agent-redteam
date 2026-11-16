"""Batch-run AgentDojo: utility on user tasks, then attacks on injection pairs.

Writes one JSON summary so results can be compared with published numbers instead of
re-running tasks one at a time.

usage:
  python3 batch.py --suite banking --attack important_instructions \
      --user-tasks 5 --injections 3 --out ~/dojo-batch.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import time
from pathlib import Path

from openai import OpenAI

from adapter import RecordingExecutor, build_pipeline
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--api-base", default="http://localhost:8081/v1")
    ap.add_argument("--suite", default="banking")
    ap.add_argument("--attack", default="important_instructions")
    ap.add_argument("--user-tasks", type=int, default=5, help="how many user tasks")
    ap.add_argument("--injections", type=int, default=3, help="injection tasks per user task")
    ap.add_argument("--out", default="dojo-batch.json")
    args = ap.parse_args()

    client = OpenAI(base_url=args.api_base, api_key=os.getenv("OPENAI_API_KEY", "local"))
    suite = get_suite("v1", args.suite)
    user_ids = list(suite.user_tasks)[: args.user_tasks]
    inj_ids = list(suite.injection_tasks)[: args.injections]

    results = []
    t0 = time.time()

    # 1) utility: user tasks alone, no injection
    utility_hits = 0
    for uid in user_ids:
        pipeline, recorder = build_pipeline(client, args.model)
        task = suite.user_tasks[uid]
        try:
            utility, _ = suite.run_task_with_pipeline(
                pipeline, task, injection_task=None, injections={})
        except Exception as e:  # noqa: BLE001
            utility = False
            print(f"[utility] {uid} ERROR {e!r}"[:160], flush=True)
        utility_hits += bool(utility)
        print(f"[utility] {uid}: {utility}", flush=True)
        results.append({"kind": "utility", "user_task": uid, "utility": bool(utility),
                        "calls": [{"function": f, "args": a} for f, a, _ in recorder.calls]})

    # 2) attacks on selected pairs
    attack_hits = 0
    pairs = list(itertools.product(user_ids, inj_ids))
    for uid, iid in pairs:
        pipeline, recorder = build_pipeline(client, args.model)
        try:
            attack = load_attack(args.attack, suite, pipeline)
            injections = attack.attack(suite.user_tasks[uid], suite.injection_tasks[iid])
            utility, security = suite.run_task_with_pipeline(
                pipeline, suite.user_tasks[uid],
                injection_task=suite.injection_tasks[iid], injections=injections)
        except Exception as e:  # noqa: BLE001
            print(f"[attack] {uid} x {iid} ERROR {e!r}"[:160], flush=True)
            continue
        attack_hits += bool(security)
        print(f"[attack] {uid} x {iid}: utility={utility} injected={security}", flush=True)
        results.append({"kind": "attack", "user_task": uid, "injection_task": iid,
                        "attack": args.attack, "utility": bool(utility),
                        "injected": bool(security),
                        "calls": [{"function": f, "args": a, "output": o[:300]}
                                  for f, a, o in recorder.calls]})

    summary = {
        "model": args.model,
        "suite": args.suite,
        "attack": args.attack,
        "utility_rate": round(utility_hits / max(len(user_ids), 1), 3),
        "attack_success_rate": round(attack_hits / max(len(pairs), 1), 3),
        "user_tasks": user_ids,
        "injection_tasks": inj_ids,
        "duration_s": round(time.time() - t0, 1),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nutility {summary['utility_rate']} | attack success "
          f"{summary['attack_success_rate']} | {summary['duration_s']}s -> {args.out}")


if __name__ == "__main__":
    main()
