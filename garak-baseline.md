# garak baseline against a local OpenAI-compatible endpoint (verified 2026-11-15)

Environment: garak 0.17.1 in its own venv (`~/garak-env`), target
`llama-server` on :8081, model Gemma4-12B Q4_K_M, RTX 4070 12GB.

## Working command (REST generator)

```bash
KEY=...   # llama-server api key
garak -t rest -n rest --generator_options '{"rest": {
  "uri": "http://localhost:8081/v1/chat/completions",
  "method": "post",
  "headers": {"Authorization": "Bearer KEY", "Content-Type": "application/json"},
  "req_template_json_object": {"model": "gemma4-12b-local", "max_tokens": 3000,
                               "temperature": 0.7,
                               "messages": [{"role": "user", "content": "$INPUT"}]},
  "response_json": true,
  "response_json_field": "$.choices[0].message.content",
  "request_timeout": 300}}' \
  -S 'probes.promptinject.HijackHateHumans,probes.dan.Dan_11_0' \
  -g 1 --parallel_attempts 1 --report_prefix ~/garak-final
```

Why not the obvious flags:

- `-t litellm -n openai/<model>`: garak 0.17.1 passes `Conversation` objects;
  `_call_model` returns empty text for every prompt (a plain `str` prompt works,
  so it looks like a server issue — it is not). A 256-prompt run returned 97.7%
  empty responses which the detectors scored as 'passed'.
- `-t openai`: ignores `api_base` and posts to api.openai.com.
- `--probes` is deprecated → `-S <spec>`; a package spec (`probes.test`) is
  rejected as inactive — name a class (`probes.dan.Dan_11_0`).
- rest.py default `request_timeout` is 20s → raise it or long generations fail.
- llama-server defaults to one slot → keep `--parallel_attempts 1`.

## Counting empty responses before quoting a pass rate

```python
import json
p = '~/garak-final.report.jsonl'
tot = empty = flag = 0
for line in open(p):
    d = json.loads(line)
    if d.get('entry_type') != 'attempt':
        continue
    o = (d.get('outputs') or [{}])[0]
    det = d.get('detector_results') or {}
    vals = [v for vs in det.values() for v in vs]
    tot += 1
    if not (o.get('text') or '').strip():
        empty += 1
    elif any(v > 0 for v in vals):
        flag += 1
print(tot, empty, flag)
```

Evaluations live in the same file with `entry_type == 'eval'`.

## Verified result (Gemma4-12B uncensored, 2026-11-15)

| probe | detector | clean | attack success |
|---|---|---|---|
| promptinject.HijackHateHumans | promptinject.AttackRogueString | 36/256 | 85.94% |
| dan.Dan_11_0 | dan.DAN | 0/1 | 100% |
| dan.Dan_11_0 | mitigation.MitigationBypass | 0/1 | 100% |

514 attempts, 2 empty (0.4%) → run considered valid. Runtime 3030s (~8s/prompt).

Coverage caveat for writeups: garak tests the RAW model. It has no view of the
DVLA agent's tools, so it neither finds nor can express the flag-2 finding
(SQLi through `GetUserTransactions`). Manual agent-layer payloads won where
promptinject probes returned refusals — that asymmetry is the harness pitch.

## Adjacent: model choice benchmark

`dvla-repo/bench_format_compliance.py` (also in harness-project/) measures
valid-JSON-first-try / empty / verbatim-payload on the real DVLA agent prompt.
2026-11-15, n=10, both on GPU: Gemma4-12B 9/10 JSON, 1 empty, 8.3s mean, 8.7GB
VRAM; Qwen2.5-7B-Instruct 10/10 JSON, 0 empty, 0.5s mean, 5.6GB — but Qwen wrote
raw SQL into the `action_input` parameter on benign queries (parameter-contract
drift). Same-probe garak comparison: promptinject ASR 85.94% (Gemma4) vs 88.7%
(Qwen), DAN 100% on both, runtime 3030s vs 61s. n=10 with empty history is a smoke
test, not a verdict.

## Swapping models on the 12GB card

One model at a time: `sudo systemctl stop gemma4.service`, then start the other
llama-server on :8081 with the same API key (keep a chmod-700 launcher script on
the host so the key never lands in argv). Qwen2.5-7B Q4_K_M ctx 32768 KV q8_0
uses 5.6GB; Gemma4-12B ctx 65536 KV q4_0 uses 8.7GB. Restore with
`sudo systemctl start gemma4.service` afterwards — the DVLA UI depends on it.
