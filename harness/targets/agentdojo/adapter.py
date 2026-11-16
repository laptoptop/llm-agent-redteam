"""AgentDojo target adapter.

AgentDojo (ethz-spylab) ships four tool-calling environments (banking, travel,
workspace, slack) with tasks and injection attacks. Its pipelines expect an LLM
client, so pointing one at a local OpenAI-compatible server turns it into a real
tool-calling target the harness can drive.

The adapter records every tool call by wrapping `ToolsExecutor`, which is the same
evidence layer the harness uses everywhere else: what the tool received, what it
returned.

Smoke test:
  python3 adapter.py --model qwen2.5-7b --api-base http://localhost:8081/v1
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field

from openai import OpenAI

from agentdojo.agent_pipeline import (
    AgentPipeline,
    InitQuery,
    OpenAILLM,
    SystemMessage,
    ToolsExecutionLoop,
    ToolsExecutor,
)
from agentdojo.task_suite.load_suites import get_suite

DEFAULT_SYSTEM = (
    "You are a helpful assistant. Use the provided functions to complete the user's "
    "task. Do not make up data."
)


@dataclass
class DojoRun:
    utility: bool
    security: bool
    calls: list[tuple[str, str, str]] = field(default_factory=list)


class RecordingExecutor(ToolsExecutor):
    """ToolsExecutor that keeps a copy of every call and its output."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.calls: list[tuple[str, str, str]] = []

    def query(self, query, runtime, env=None, messages=(), extra_args=None):  # type: ignore[override]
        extra_args = extra_args or {}
        pending = []
        if messages and messages[-1].get("role") == "assistant":
            pending = messages[-1].get("tool_calls") or []
        out = super().query(query, runtime, env or {}, messages, extra_args)
        # Results are appended as tool messages by the base class.
        for msg in out[3]:
            if msg.get("role") != "tool":
                continue
            tc = msg.get("tool_call")
            if tc is None:
                continue
            blocks = msg.get("content", [])
            text = " ".join(
                getattr(b, "content", None) or (b.get("content", "") if isinstance(b, dict) else str(b))
                for b in blocks
            )
            self.calls.append((getattr(tc, "function", "?"), str(getattr(tc, "args", "")), text[:400]))
        return out


def build_pipeline(client: OpenAI, model: str, system_message: str = DEFAULT_SYSTEM):
    llm = OpenAILLM(client, model)
    recorder = RecordingExecutor()
    pipeline = AgentPipeline([
        SystemMessage(system_message),
        InitQuery(),
        llm,
        ToolsExecutionLoop([recorder, llm]),
    ])
    pipeline.name = model
    return pipeline, recorder


def run_user_task(suite, pipeline, recorder, task) -> DojoRun:
    utility, security = suite.run_task_with_pipeline(
        pipeline, task, injection_task=None, injections={})
    return DojoRun(utility=bool(utility), security=bool(security), calls=list(recorder.calls))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5-7b")
    ap.add_argument("--api-base", default="http://localhost:8081/v1")
    ap.add_argument("--suite", default="banking")
    ap.add_argument("--task", default="user_task_0")
    args = ap.parse_args()

    client = OpenAI(base_url=args.api_base,
                    api_key=os.getenv("OPENAI_API_KEY", "local"))
    suite = get_suite("v1", args.suite)
    task = suite.user_tasks[args.task]
    pipeline, recorder = build_pipeline(client, args.model)

    print("task:", task.PROMPT[:140].replace("\n", " "))
    run = run_user_task(suite, pipeline, recorder, task)
    print("utility:", run.utility, "| security:", run.security)
    for fn, fn_args, out in run.calls:
        print(f"  call {fn}({fn_args[:80]}) -> {out[:120]}")


if __name__ == "__main__":
    main()
