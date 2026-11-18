"""Score a predictions_dev.jsonl against data/ground_truth/dev.jsonl: routing (missed and unnecessary reviews),
review reasons, required approvals and field accuracy, with and without the three dev documents the starter leaked
into its prompt, and with skipped documents counted as failures.

Usage (from backend/):  python eval/score_predictions.py .. <predictions_dev.jsonl>
"""
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
pred_file = Path(sys.argv[2])
LEAKED = {"dev_001", "dev_002", "dev_003"}  # first 3 rows of dev.jsonl are pasted into the starter's prompt
FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
          "subtotal", "cgst", "sgst", "igst", "total", "po_number"]  # the 12 fields run_eval.py scores

gt = {json.loads(l)["document_id"]: json.loads(l)["expected"]
      for l in open(repo / "data/ground_truth/dev.jsonl", encoding="utf-8")}
pred = {json.loads(l)["document_id"]: json.loads(l) for l in open(pred_file, encoding="utf-8")}


def norm(v):  # identical to run_eval._norm
    if v is None:
        return ""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v).strip().lower()


def field_acc(ids, failed_count_as_wrong):
    correct = total = 0
    for d in ids:
        if d not in pred:
            if failed_count_as_wrong:
                total += len(FIELDS)
            continue
        for f in FIELDS:
            total += 1
            correct += norm(pred[d].get(f)) == norm(gt[d].get(f))
    return correct, total


all_ids = sorted(gt)
clean_ids = [d for d in all_ids if d not in LEAKED]
print("FIELD ACCURACY (run_eval method: 12 fields, exact match after normalisation)")
for label, ids, strict in [("as run_eval does it (all 24, skipped docs dropped)", all_ids, False),
                           ("leaked dev_001-003 removed, skipped docs dropped", clean_ids, False),
                           ("leaked removed AND skipped/failed docs counted as wrong", clean_ids, True),
                           ("all 24, failed docs counted as wrong", all_ids, True)]:
    c, t = field_acc(ids, strict)
    print(f"  {label:58s} {c}/{t} = {c / t:.1%}" if t else f"  {label}: n/a")

print("\nPER-FIELD errors (non-leaked docs)")
for f in FIELDS:
    wrong = [d for d in clean_ids if d in pred and norm(pred[d].get(f)) != norm(gt[d].get(f))]
    if wrong:
        print(f"  {f:15s} {len(wrong)} wrong: " + ", ".join(
            f"{d}(got {pred[d].get(f)!r}, want {gt[d].get(f)!r})" for d in wrong[:4]) + (" ..." if len(wrong) > 4 else ""))

print("\nROUTING (needs_review) vs labels")
missed = [d for d in all_ids if gt[d]["needs_review"] and d in pred and not pred[d]["needs_review"]]
unnec = [d for d in all_ids if not gt[d]["needs_review"] and d in pred and pred[d]["needs_review"]]
skipped = [d for d in all_ids if d not in pred]
need = sum(gt[d]["needs_review"] for d in all_ids)
print(f"  labelled needs_review: {need}/24 | missed reviews (should review, routed READY): {len(missed)} {missed}")
print(f"  unnecessary reviews (clean, routed to review): {len(unnec)} {unnec}")
print(f"  skipped (no line, no processing_error): {len(skipped)} {skipped}")

print("\nREASON-LEVEL and APPROVAL differences (every doc, incl. leaked)")
for d in all_ids:
    if d not in pred:
        continue
    want, got = set(gt[d]["review_reasons"]), set(pred[d]["review_reasons"])
    appr_want, appr_got = gt[d]["required_approvals"], pred[d]["required_approvals"]
    issues = []
    if want - got:
        issues.append(f"MISSING {sorted(want - got)}")
    if got - want:
        issues.append(f"EXTRA {sorted(got - want)}")
    if appr_want != appr_got:
        issues.append(f"approvals {appr_got} (policy: {appr_want})")
    if issues:
        tag = "LEAKED " if d in LEAKED else ""
        print(f"  {tag}{d}: routed {'REVIEW' if pred[d]['needs_review'] else 'READY '} "
              f"(label {'REVIEW' if gt[d]['needs_review'] else 'READY '}) | " + " | ".join(issues))
