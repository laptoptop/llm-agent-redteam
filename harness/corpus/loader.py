"""Corpus loader.

A corpus is a YAML list of payloads with an expected impact type. Keeping payloads
data (not code) means third-party corpora - HackMyAgent (Apache-2.0), garak probes -
can be converted and credited instead of vendored into this repo.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED = ("id", "category", "name", "expected_impact", "payload")
IMPACTS = ("tool_argument", "tool_output", "data_egress", "answer_leak")


def load(path: str | Path) -> list[dict]:
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a YAML list of payloads")
    for e in entries:
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            raise ValueError(f"{path}: entry {e.get('id', '?')} missing {missing}")
        if e["expected_impact"] not in IMPACTS:
            raise ValueError(f"{path}: {e['id']} has unknown expected_impact "
                             f"{e['expected_impact']!r} (allowed: {IMPACTS})")
    return entries
