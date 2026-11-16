"""Run AgentDojo injection tasks and record what actually reached the tools.

AgentDojo reports `security: bool` per (user task, injection task) pair. That flag is
the benchmark's own verdict; this runner adds the evidence layer - the tool calls and
arguments the agent produced - so a finding can be read without trusting the flag.

usage:
  python3 run_injection.py --suite banking --user-task user_task_0 \
      --injection-task injection_task_0 --attack important_instructions
"""
from __future__ import annotations

import argparse
import json
import os
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
    ap.add_argument("--user-task", default="user_task_0")
    ap.add_argument("--injection-task", default="injection_task_0")
    ap.add_argument("--attack", default="important_instructions")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    client = OpenAI(base_url=args.api_base, api_key=os.getenv("OPENAI_API_KEY", "local"))
    suite = get_suite("v1", args.suite)
    user_task = suite.user_tasks[args.user_task]
    injection_task = suite.injection_tasks[args.injection_task]

    pipeline, recorder = build_pipeline(client, args.model)
    attack = load_attack(args.attack, suite, pipeline)
    injections = attack.attack(user_task, injection_task)

    print(f"user task: {user_task.PROMPT[:100]!r}")
    print(f"injection goal: {injection_task.GOAL[:100]!r}")
    print(f"attack: {args.attack}; injected into {list(injections)}")

    utility, security = suite.run_task_with_pipeline(
        pipeline, user_task, injection_task=injection_task, injections=injections)

    print(f"\nutility: {utility} | security (benchmark verdict): {security}")
    print("tool calls:")
    for fn, fn_args, out in recorder.calls:
        print(f"  {fn}({fn_args[:90]})")
        if out:
            print(f"      -> {out[:110]}")

    record = {
        "model": args.model,
        "suite": args.suite,
        "user_task": args.user_task,
        "injection_task": args.injection_task,
        "attack": args.attack,
        "utility": bool(utility),
        "security": bool(security),
        "injection_goal": injection_task.GOAL,
        "calls": [{"function": f, "args": a, "output": o[:400]}
                  for f, a, o in recorder.calls],
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
