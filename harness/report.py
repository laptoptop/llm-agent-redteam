"""Markdown report writer.

One section per finding: payload, tool-call trace, impact. The trace is the point —
a reviewer can see the SQL fragment arriving at the tool and the password coming back
without trusting the harness's own verdict.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from tracing import Finding


def _fence(text: str, limit: int = 1200) -> str:
    text = text if len(text) <= limit else text[:limit] + "\n… (truncated)"
    return f"```\n{text}\n```"


def render(findings: list[Finding], target_desc: str) -> str:
    out: list[str] = []
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    hits = sum(1 for f in findings if f.vulnerable)

    out.append("# Agent red-team run\n")
    out.append(f"- **Target:** {target_desc}")
    out.append(f"- **Date:** {stamp}")
    out.append(f"- **Runs:** {len(findings)} · **Exploited:** {hits}\n")

    out.append("## Summary\n")
    out.append("| Module | Model | Result |")
    out.append("|---|---|---|")
    for f in findings:
        verdict = "**VULNERABLE**" if f.vulnerable else "not exploitable"
        out.append(f"| {f.module} | `{f.model}` | {verdict} |")
    out.append("")

    for f in findings:
        out.append(f"## {f.module} — {'VULNERABLE' if f.vulnerable else 'no finding'}\n")
        out.append(f"**{f.title}**\n")
        out.append(f"- Model: `{f.model}`")
        out.append(f"- Impact: {f.impact}")
        out.append(f"- Evidence: {f.evidence}")
        out.append(f"- Duration: {f.trace.duration_s}s")
        if f.trace.error:
            out.append(f"- Error: `{f.trace.error}`")
        out.append("\n**Payload**\n")
        out.append(_fence(f.trace.payload))
        out.append("\n**Tool-call trace**\n")
        if not f.trace.tool_calls:
            out.append("_no tool calls_\n")
        for call in f.trace.tool_calls:
            out.append(f"{call.step}. `{call.tool}` input={call.tool_input!r}")
            out.append(_fence(call.observation, limit=600))
        out.append("\n**Final answer**\n")
        out.append(_fence(f.trace.final_answer, limit=600))
        out.append("")

    return "\n".join(out)


def write(findings: list[Finding], target_desc: str, out_path: str) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(findings, target_desc), encoding="utf-8")
    return path
