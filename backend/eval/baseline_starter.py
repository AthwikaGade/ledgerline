"""Baseline measurement of the starter pipeline. Diagnostic tooling only: it does not modify application code.

It runs the starter's own entry points (`ledgerline.cli.main` and `eval/run_eval.py`) with the LLM client
wrapped by a recorder that:
  * caches every raw model response on disk (reused on later runs, so the same prompt is never paid for twice);
  * logs every call (document, tokens, latency, real cost, cache hit or miss, errors);
  * enforces a hard cap on new API calls and on cumulative spend;
  * in `unwrap` mode only, strips Markdown fences/prose around the JSON before the starter parses it.

Runs, each written to submission/baseline/<model>/<folder>/ with a CODE_VERSION.txt naming the code that produced it:
  A_starter_unchanged                    -> the starter's actual behaviour, response text passed through untouched
  B_DIAGNOSTIC_starter_plus_json_unwrap  -> NOT the original baseline: starter + a JSON-unwrap shim, to measure the
                                            starter's logic once its responses can be parsed
  C_current_code_cached_replay           -> later code replaying A/B's cached responses (no API calls)
  D_improved_pipeline                    -> the improved pipeline on real calls (optionally with an escalation model)

Run from backend/ (PowerShell or Git Bash). A and B were recorded at the starter commit; on later code they are
refused unless --allow-legacy-mode is given, so recorded evidence is never overwritten by different code.
  python eval/baseline_starter.py --dry-run                                   # offline, no API calls, no key needed
  python eval/baseline_starter.py --mode improved --model claude-opus-5-5     # same model as the starter
  python eval/baseline_starter.py --mode improved --model claude-haiku-5-5 --escalation-model claude-opus-5-5
Then score a run against the dev labels:
  python eval/score_predictions.py .. ../submission/baseline/<run>/<folder>/predictions_dev.jsonl

Raw responses are cached under submission/baseline/llm_cache/ (git-ignored: never committed). Spend is capped by
--max-usd (cumulative over every model's ledger) and --max-calls (new calls in this run, all models together).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "eval"))

import run_eval  # noqa: E402  (the starter's own eval script)
import ledgerline.cli as cli  # noqa: E402
import ledgerline.extraction as extraction  # noqa: E402
from ledgerline.config import USD_TO_INR  # noqa: E402
from ledgerline.llm.base import LLMResponse  # noqa: E402

# Anthropic list prices, USD per million tokens (input, output), checked 18 Nov 2026.
# The starter's own table (ledgerline/llm/pricing.py) is 1,000x too low, so it is NOT used here.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
MODES = {
    "unchanged": ("A_starter_unchanged",
                  "Starter's ACTUAL behaviour. Model responses passed through untouched."),
    "unwrap": ("B_DIAGNOSTIC_starter_plus_json_unwrap",
               "DIAGNOSTIC ONLY, NOT THE ORIGINAL BASELINE. Starter + a JSON-unwrap shim that strips Markdown "
               "fences/prose around the model's JSON. Everything else is the unchanged starter."),
    "improved": ("D_improved_pipeline",
                 "The CURRENT pipeline (code routing, masking, one call per document, optional escalation), on real "
                 "model calls. Same model as the starter baseline when run with --model claude-opus-5-5."),
    "replay": ("C_current_code_cached_replay",
               "CURRENT working-tree code, replaying the cached model responses recorded in runs A/B (same prompts, "
               "same model). Run with --max-calls 0 so it can never make a new API call."),
}
SPLITS = {"dev": REPO / "data" / "invoices" / "dev", "disputed": REPO / "data" / "invoices" / "disputed"}
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")
FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


class BudgetExceeded(BaseException):
    """Deliberately not an Exception: the starter's `except Exception` must not swallow it and keep going."""


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def unwrap(text: str) -> tuple[str, str]:
    """Return (json_text, kind) where kind is none | fence | brace | failed."""
    try:
        json.loads(text)
        return text, "none"
    except ValueError:
        pass
    match = FENCE.search(text)
    if match:
        candidate, kind = match.group(1), "fence"
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return text, "failed"
        candidate, kind = text[start:end + 1], "brace"
    try:
        json.loads(candidate)
        return candidate, kind
    except ValueError:
        return text, "failed"


def percentile(values: list[int], p: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


class _DryRunClient:
    """Offline stand-in: returns the response shape Opus 5.5 actually produced (fenced JSON + a prose paragraph)."""

    def __init__(self, model: str, fail: bool = False):
        from ledgerline.llm.fake import CANNED_EXTRACTION
        self.model, self.fail = model, fail
        self.text = "```json\n" + json.dumps(CANNED_EXTRACTION, indent=2) + "\n```\n\nSome explanation."

    def complete(self, system: str, prompt: str, max_tokens: int = 16000) -> LLMResponse:
        text = "Sorry, I cannot read this." if self.fail else self.text  # 'fail' exercises the escalation path
        return LLMResponse(text, self.model, len(prompt) // 4, len(text) // 4, 1)


class Budget:
    """One cap for every model in the run: new API calls in this run, and cumulative spend across all runs (the sum
    of every model's spend ledger under the cache root)."""

    def __init__(self, cache_root: Path, max_calls: int, max_usd: float):
        self.max_calls, self.max_usd = max_calls, max_usd
        self.spent_before = sum(json.loads(line)["billed_usd"]
                                for ledger in cache_root.glob("*/spend_ledger.jsonl")
                                for line in ledger.open(encoding="utf-8"))
        self.spent_now, self.new_calls = 0.0, 0

    def check(self) -> None:
        if self.new_calls >= self.max_calls:
            raise BudgetExceeded(f"max new API calls reached ({self.max_calls})")
        if self.spent_before + self.spent_now >= self.max_usd:
            raise BudgetExceeded(f"spend cap reached (${self.spent_before + self.spent_now:.2f} of ${self.max_usd})")


class Context:
    """Shared by the primary and escalation recorders: which document is being processed, and every call made."""

    def __init__(self):
        self.split = self.doc = None
        self.call_no = 0
        self.calls: list[dict] = []
        self.failures: list[dict] = []


class Recorder:
    def __init__(self, model: str, mode: str, cache_dir: Path, budget: Budget, ctx: Context, dry_run: bool,
                 provider: str | None = None, role: str = "primary", dry_run_fails: bool = False):
        self.model, self.mode, self.cache_dir, self.budget, self.ctx = model, mode, cache_dir, budget, ctx
        self.dry_run, self.provider, self.role, self.dry_run_fails = dry_run, provider, role, dry_run_fails
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.spend_ledger = self.cache_dir / "spend_ledger.jsonl"
        self.inner = None

    # Back-compatible views used by summarize()
    @property
    def calls(self):
        return self.ctx.calls

    @property
    def failures(self):
        return self.ctx.failures

    # -- the LLMClient interface the pipeline calls ------------------------------------------------
    def complete(self, system: str, prompt: str, max_tokens: int | None = None) -> LLMResponse:
        self.ctx.call_no += 1
        key = hashlib.sha256(json.dumps([self.model, system, prompt, max_tokens]).encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{key}.json"
        entry = {"split": self.ctx.split, "document_id": self.ctx.doc, "call_no": self.ctx.call_no,
                 "model": self.model, "role": self.role, "cache_key": key[:16]}
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            entry.update(cache="hit", billed_usd=0.0)
        else:
            record = self._call_api(system, prompt, max_tokens, key, entry)
            path_tmp = path.with_suffix(".tmp")
            path_tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            path_tmp.replace(path)
            entry.update(cache="miss", billed_usd=record["cost_usd"])
        text = record["text"]
        kind = "passthrough"
        if self.mode == "unwrap":
            text, kind = unwrap(text)
        entry.update(input_tokens=record["input_tokens"], output_tokens=record["output_tokens"],
                     latency_ms=record["latency_ms"], token_cost_usd=record["cost_usd"], unwrap=kind,
                     response_starts_with=record["text"][:12])
        self.ctx.calls.append(entry)
        return LLMResponse(text, record["model"], record["input_tokens"], record["output_tokens"],
                           record["latency_ms"])

    def _call_api(self, system, prompt, max_tokens, key, entry) -> dict:
        self.budget.check()  # shared by primary and escalation
        if self.inner is None:
            if self.dry_run:
                self.inner = _DryRunClient(self.model, fail=self.dry_run_fails)
            else:
                from ledgerline.llm import _build
                self.inner = _build(self.provider or os.getenv("LLM_PROVIDER", "anthropic"), self.model)
        self.budget.new_calls += 1
        try:
            resp = self.inner.complete(system, prompt) if max_tokens is None \
                else self.inner.complete(system, prompt, max_tokens)
        except Exception as exc:  # recorded, never cached, then re-raised so the pipeline behaves as it would
            entry.update(cache="miss", error=f"{type(exc).__name__}: {SECRET.sub('[hidden]', str(exc))[:300]}")
            self.ctx.calls.append(dict(entry))
            raise
        if SECRET.search(resp.text):
            raise BudgetExceeded("response contains something that looks like an API key; refusing to save it")
        billed = cost_usd(self.model, resp.input_tokens, resp.output_tokens)
        self.budget.spent_now += billed
        with self.spend_ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "key": key[:16],
                                "billed_usd": round(billed, 6)}) + "\n")
        return {"model": resp.model, "created_at": datetime.now(timezone.utc).isoformat(), "text": resp.text,
                "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                "latency_ms": resp.latency_ms, "cost_usd": round(billed, 6)}

    # -- per-document context, so every call and failure is attributed to a document ---------------
    def trace(self, process_document):
        def traced(conn, ref, raw_text, document_id, **kwargs):
            self.ctx.doc, self.ctx.call_no = document_id, 0
            try:
                return process_document(conn, ref, raw_text, document_id, **kwargs)
            except Exception as exc:
                self.ctx.failures.append({"split": self.ctx.split, "document_id": document_id,
                                      "error": f"{type(exc).__name__}: {SECRET.sub('[hidden]', str(exc))[:300]}"})
                raise
        return traced


def summarize(rec: Recorder, out_dir: Path, eval_result: dict, label: str) -> dict:
    summary = {"label": label, "mode": rec.mode, "model": rec.model,
               "generated_at": datetime.now(timezone.utc).isoformat(), "splits": {}, "eval": eval_result}
    for split, folder in SPLITS.items():
        docs = sorted(p.stem for p in folder.iterdir() if p.suffix in cli.SUPPORTED_SUFFIXES)
        pred_file = out_dir / f"predictions_{split}.jsonl"
        preds = [json.loads(l) for l in pred_file.open(encoding="utf-8")] if pred_file.exists() else []
        written = {p["document_id"] for p in preds}
        calls = [c for c in rec.calls if c["split"] == split and "error" not in c]
        per_doc_latency, per_doc_cost = {}, {}
        for c in calls:
            per_doc_latency[c["document_id"]] = per_doc_latency.get(c["document_id"], 0) + c["latency_ms"]
            per_doc_cost[c["document_id"]] = per_doc_cost.get(c["document_id"], 0) + c["token_cost_usd"]
        unwrap_counts: dict[str, int] = {}
        for c in calls:
            unwrap_counts[c["unwrap"]] = unwrap_counts.get(c["unwrap"], 0) + 1
        avg_cost = sum(per_doc_cost.values()) / len(per_doc_cost) if per_doc_cost else 0.0
        summary["splits"][split] = {
            "documents": len(docs),
            "predictions_written": len(written),
            "documents_skipped": sorted(set(docs) - written),
            "llm_calls": len(calls),
            "cache_hits": sum(c["cache"] == "hit" for c in calls),
            "api_errors": sum(1 for c in rec.calls if c["split"] == split and "error" in c),
            "response_handling": unwrap_counts,
            "real_cost_per_doc_usd_avg": round(avg_cost, 4),
            "real_cost_per_doc_inr_avg": round(avg_cost * USD_TO_INR, 2),
            "latency_per_doc_ms_p50": percentile(list(per_doc_latency.values()), 50),
            "latency_per_doc_ms_p95": percentile(list(per_doc_latency.values()), 95),
            "starter_reported_cost_inr_total": round(sum(p["usage"]["cost_inr"] for p in preds), 4),
            "real_cost_inr_total_for_written_docs": round(
                sum(per_doc_cost.get(d, 0) for d in written) * USD_TO_INR, 2),
        }
    summary["new_api_calls_this_run"] = rec.budget.new_calls
    summary["billed_usd_this_run"] = round(rec.budget.spent_now, 4)
    summary["billed_usd_all_runs"] = round(rec.budget.spent_before + rec.budget.spent_now, 4)
    by_model: dict[str, dict] = {}
    for c in rec.calls:
        if c["split"] in SPLITS and "error" not in c:
            m = by_model.setdefault(c.get("model", rec.model), {"calls": 0, "cost_usd": 0.0, "role": c.get("role")})
            m["calls"] += 1
            m["cost_usd"] = round(m["cost_usd"] + c["token_cost_usd"], 6)
    summary["calls_by_model"] = by_model
    summary["failures"] = rec.failures
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="unchanged")
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", "claude-opus-5-5"))
    ap.add_argument("--max-calls", type=int, default=60, help="hard cap on NEW (uncached) API calls in this run")
    ap.add_argument("--max-usd", type=float, default=8.0, help="hard cap on cumulative spend across all runs")
    ap.add_argument("--dry-run", action="store_true", help="offline: fake responses, temp output, no API calls")
    ap.add_argument("--out-root", default=None, help="override the output root (default: submission/baseline)")
    ap.add_argument("--run-label", default=None, help="suffix for the output folder, e.g. a commit id")
    ap.add_argument("--escalation-model", default=None, help="improved mode: model used when the primary fails")
    ap.add_argument("--escalation-provider", default=None, help="provider of the escalation model (default: same)")
    ap.add_argument("--dry-run-primary-fails", action="store_true", help="dry run: make the primary fail, to "
                    "exercise escalation")
    ap.add_argument("--allow-legacy-mode", action="store_true", help="allow re-running unchanged/unwrap on the "
                    "current code (their recorded results were produced on the starter code; re-running would "
                    "overwrite them with something else)")
    args = ap.parse_args()
    for model in filter(None, [args.model, args.escalation_model]):
        if model not in PRICES:
            sys.exit(f"No price for model {model!r}; add it to PRICES first.")
    if args.mode in ("unchanged", "unwrap") and not (args.dry_run or args.allow_legacy_mode):
        sys.exit(f"Mode {args.mode!r} describes the STARTER and was recorded at commit 6e59f77; the code has changed "
                 f"since. Use --mode improved for the current pipeline (or --allow-legacy-mode if you really mean it).")
    os.environ["LLM_MODEL"] = args.model

    if args.out_root:
        root = Path(args.out_root)
    elif args.dry_run:
        root = Path(tempfile.mkdtemp(prefix="baseline-dry-"))
    else:
        root = REPO / "submission" / "baseline"
    folder, label = MODES[args.mode]
    run_name = args.model + (f"+escalation-{args.escalation_model}" if args.escalation_model else "")
    out_dir = root / run_name / folder
    if args.run_label:
        out_dir = out_dir.with_name(f"{folder}_{args.run_label}")
    # Never mix code versions: refuse to write into a run folder recorded by different code.
    code = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                          cwd=REPO).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "backend/ledgerline"], capture_output=True, text=True,
                           cwd=REPO).stdout.strip()
    version = f"code: commit {code}{' + uncommitted changes in backend/ledgerline' if dirty else ' (clean tree)'}"
    marker = out_dir / "CODE_VERSION.txt"
    if marker.exists() and not args.dry_run and marker.read_text(encoding="utf-8").splitlines()[0] != version:
        sys.exit(f"{out_dir} was recorded by different code ({marker.read_text(encoding='utf-8').splitlines()[0]}); "
                 f"refusing to overwrite it. Use --run-label to write a new folder.")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(version + "\n", encoding="utf-8")
    (out_dir / "LABEL.txt").write_text(label + "\n", encoding="utf-8")
    cache_root = root / "llm_cache"
    budget, ctx = Budget(cache_root, args.max_calls, args.max_usd), Context()
    rec = Recorder(args.model, args.mode, cache_root / args.model, budget, ctx, args.dry_run,
                   dry_run_fails=args.dry_run_primary_fails)
    escalation = None
    if args.escalation_model:
        escalation = Recorder(args.escalation_model, args.mode, cache_root / args.escalation_model, budget, ctx,
                              args.dry_run, provider=args.escalation_provider, role="escalation")

    # The only patch points: the clients the pipeline asks for. Both are cached, recorded and capped.
    extraction.get_client = lambda: rec
    extraction.get_escalation_client = lambda: escalation
    cli.process_document = rec.trace(cli.process_document)
    run_eval.process_document = rec.trace(run_eval.process_document)

    eval_result: dict = {}
    try:
        for split, folder_path in SPLITS.items():
            ctx.split = split
            log = io.StringIO()
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                cli.main(["predict", "--input", str(folder_path), "--reference", str(REPO / "data" / "reference"),
                          "--output", str(out_dir / f"predictions_{split}.jsonl")])
            (out_dir / f"cli_{split}.log").write_text(log.getvalue(), encoding="utf-8")
            print(f"[{split}] {log.getvalue().strip().splitlines()[-1]}")
        ctx.split = "eval"
        log = io.StringIO()
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                run_eval.main()
            eval_result = {"status": "completed", "output": log.getvalue().strip().splitlines()[-1]}
        except Exception as exc:
            eval_result = {"status": "crashed", "error": f"{type(exc).__name__}: {exc}"}
        (out_dir / "eval.log").write_text(log.getvalue() + json.dumps(eval_result) + "\n", encoding="utf-8")
        print(f"[eval] {eval_result}")
    except BudgetExceeded as stop:
        eval_result = {"status": "aborted", "reason": str(stop)}
        print(f"ABORTED: {stop}")
    finally:
        with (out_dir / "calls.jsonl").open("w", encoding="utf-8") as f:
            for c in rec.calls:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        summary = summarize(rec, out_dir, eval_result, label)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"new API calls: {budget.new_calls} | billed this run: ${budget.spent_now:.4f} | "
              f"all runs: ${budget.spent_before + budget.spent_now:.4f} | by model: {summary['calls_by_model']}")
        print(f"outputs: {out_dir}")


if __name__ == "__main__":
    main()
