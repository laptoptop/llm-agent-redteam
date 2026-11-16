"""Tool-call level tracing for agent targets.

A chat-model scanner only ever sees prompt -> response. Agent findings live one
layer lower: which tool was called, with what argument, and what came back. This
module is the evidence store for that layer.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ToolCall:
    """One tool invocation observed during an agent run."""

    step: int
    tool: str
    tool_input: str
    observation: str

    def mentions(self, needle: str) -> bool:
        needle = needle.lower()
        return needle in self.tool_input.lower() or needle in self.observation.lower()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunTrace:
    """Everything that happened during one payload run."""

    module: str
    model: str
    payload: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer: str = ""
    duration_s: float = 0.0
    error: str | None = None

    def add(self, step: int, tool: str, tool_input: str, observation: str) -> None:
        self.tool_calls.append(
            ToolCall(step=step, tool=tool, tool_input=str(tool_input),
                     observation=str(observation))
        )

    def tool_names(self) -> list[str]:
        return [c.tool for c in self.tool_calls]

    def find(self, tool: str) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.tool == tool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "model": self.model,
            "payload": self.payload,
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "final_answer": self.final_answer,
            "duration_s": self.duration_s,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass
class Finding:
    """A judged outcome: exploitable or not, with the evidence that proves it."""

    module: str
    model: str
    vulnerable: bool
    title: str
    impact: str
    evidence: str
    trace: RunTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "model": self.model,
            "vulnerable": self.vulnerable,
            "title": self.title,
            "impact": self.impact,
            "evidence": self.evidence,
            "trace": self.trace.to_dict(),
        }


class Stopwatch:
    def __enter__(self) -> "Stopwatch":
        self._t0 = time.time()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.time() - self._t0
