"""Check a predictions file against docs/OUTPUT_CONTRACT.md.

Usage (from backend/):
  python eval/check_contract.py <input folder> <predictions.jsonl> [--flags-on]

Checks: one line per supported input document, in document_id order, nothing skipped; every contract field present
with the contract's type; money as two-decimal strings; ISO dates; review reasons from AP_POLICY section 3, plus the
flagged codes only when --flags-on; needs_review consistent with the reasons; usage complete; optional evidence
well-formed. A processing_error line may carry null for fields that could not be read (README, "Running my version").
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

POLICY_CODES = {"credit_note", "duplicate", "gstin_invalid", "vendor_unknown", "vendor_new", "bank_details_changed",
                "tax_type_mismatch", "totals_mismatch", "foreign_currency", "suspicious_content", "processing_error"}
FLAGGED_CODES = {"line_amount_mismatch", "future_dated"}
MONEY = ["subtotal", "cgst", "sgst", "igst", "round_off", "total"]
STRING_OR_NULL = ["supplier_gstin", "bank_account", "ifsc", "po_number"]
STRING = ["supplier_name", "invoice_number", "currency"]
USAGE = {"llm_calls", "input_tokens", "output_tokens", "cost_inr", "latency_ms"}
MONEY_RE = re.compile(r"-?\d+\.\d{2}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def check_line(line: dict, flags_on: bool) -> list[str]:
    problems = []
    unreadable = "processing_error" in (line.get("review_reasons") or [])

    def need(cond, msg):
        if not cond:
            problems.append(msg)

    need(line.get("document_type") in ("invoice", "credit_note"), "document_type")
    for f in STRING:
        need(isinstance(line.get(f), str) or (unreadable and line.get(f) is None), f)
    for f in STRING_OR_NULL:
        need(f in line and (line[f] is None or isinstance(line[f], str)), f)
    need(isinstance(line.get("invoice_date"), str) and DATE_RE.fullmatch(line["invoice_date"])
         or (unreadable and line.get("invoice_date") is None), "invoice_date")
    for f in MONEY:
        value = line.get(f, "missing")
        need(isinstance(value, str) and MONEY_RE.fullmatch(value) or (unreadable and value is None), f)
    need(isinstance(line.get("line_items"), list), "line_items")
    for i, item in enumerate(line.get("line_items") or []):
        need({"description", "quantity", "unit_price", "amount"} <= set(item), f"line_items[{i}] fields")
    reasons = line.get("review_reasons")
    allowed = POLICY_CODES | (FLAGGED_CODES if flags_on else set())
    need(isinstance(reasons, list) and set(reasons) <= allowed, f"review_reasons {reasons}")
    need(isinstance(line.get("needs_review"), bool) and line["needs_review"] == bool(reasons), "needs_review")
    need(isinstance(line.get("required_approvals"), int) and line["required_approvals"] >= 0, "required_approvals")
    need(isinstance(line.get("usage"), dict) and USAGE <= set(line["usage"]), "usage")
    for name, ev in (line.get("evidence") or {}).items():
        need({"start", "end", "text"} <= set(ev), f"evidence.{name}")
    return problems


def main(argv: list[str]) -> int:
    folder, predictions = Path(argv[0]), Path(argv[1])
    flags_on = "--flags-on" in argv
    expected = sorted((p.stem, p.name) for p in folder.iterdir() if p.suffix in {".txt", ".eml", ".json"})
    lines = [json.loads(raw) for raw in predictions.read_text(encoding="utf-8").splitlines() if raw.strip()]
    errors = []
    ids = [line.get("document_id") for line in lines]
    if ids != [stem for stem, _ in expected]:
        errors.append(f"document ids/order: expected {[s for s, _ in expected]}, got {ids}")
    for line in lines:
        for problem in check_line(line, flags_on):
            errors.append(f"{line.get('document_id')}: {problem}")
    print(f"{predictions.name}: {len(lines)} lines for {len(expected)} documents; "
          f"{'OK' if not errors else str(len(errors)) + ' problem(s)'}")
    for error in errors:
        print("  -", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
