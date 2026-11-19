# Recorded evaluation runs

Produced by `backend/eval/baseline_starter.py` on 18 Nov 2026 (Anthropic API). Each folder holds one run:
`CODE_VERSION.txt` (the code that produced it), `LABEL.txt`, `summary.json` (per-split counts, cost, latency),
`calls.jsonl` (one line per LLM call: document, model, role, tokens, latency, list-price cost, cache hit or miss,
errors; no prompt or response text), `cli_*.log`, `eval.log` and the predictions it wrote.

| Folder | Pipeline | Code | Kind |
|---|---|---|---|
| `claude-opus-5-5/A_starter_unchanged` | unchanged starter | starter `6e59f77` | real calls (30) |
| `claude-opus-5-5/B_DIAGNOSTIC_starter_plus_json_unwrap` | starter + JSON-unwrap shim (diagnostic, not the baseline) | starter + shim | real calls (30); first calls reused from A |
| `claude-opus-5-5/C_current_code_cached_replay` | A/B's responses read by Milestone 2 code | `5b8bea3` | cached replay, no calls |
| `claude-opus-5-5/D_improved_pipeline` | improved pipeline on Opus (has the quantity bug fixed later) | `2b24b53` | real calls (30) |
| `claude-haiku-5-5+escalation-claude-opus-5-5/D_improved_pipeline` | Haiku primary, Opus escalation | `4b6a0d3` | real Haiku calls (30); the 5 Opus escalations were cache hits from the Opus run above |

The final predictions (`submission/predictions_*.jsonl`) are the Haiku run's recorded responses read by code
`64a7d51`; see EVAL_REPORT, "Where each number comes from".

## What is not here, and what was changed

- **Raw model responses are not committed.** They are cached locally under `llm_cache/` (git-ignored), which is what
  makes re-scoring after a code change free.
- **Bank account numbers in these copies of the predictions are masked to their last four digits.** The data is
  fictional, but the evidence does not need them. (The final predictions keep them: OUTPUT_CONTRACT asks for the
  digits as printed.)
- **Machine-specific paths in the logs are replaced** by `<repo>` / `<tmp>`. Nothing else was edited.
