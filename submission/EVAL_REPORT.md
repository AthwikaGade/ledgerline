# Evaluation Report

## Setup

I tested Ledgerline on **18 November 2026** using Anthropic's Claude Opus 5.5 and Haiku 5.5.

I used **30 invoices**: 24 development invoices and 6 disputed invoices.

The results are saved in `submission/baseline/`. The evaluation can be repeated from the `backend/` folder:

```bash
python eval/baseline_starter.py --mode improved --model claude-opus-5-5
python eval/baseline_starter.py --mode improved --model claude-haiku-5-5 --escalation-model claude-opus-5-5
```

Some final results used saved model responses with updated code instead of making new API calls. This saved money, but it is not the same as a fresh test.

## What the "94%" actually measured

The starter claimed **94.2% accuracy**, but it only checked whether 12 invoice fields were extracted correctly. It did not check payment safety.

When I ran the original starter, it failed to process all 24 development invoices because it couldn't read the model's JSON responses.

After fixing only that reading problem for testing, I got **99.7% field accuracy**, but the system still missed 2 duplicate invoices.

I also found that three development invoices and their answers were already included in the model's prompt. Removing those from the scoring calculation reduced accuracy to **99.6%**. I did not rerun the model without them in the prompt, so this result still has some data leakage.

## What I chose to measure, and why

I mainly checked:

- **Missed reviews:** Invoices that should be reviewed but are marked ready.
- **Unnecessary reviews:** Correct invoices sent for review, costing about ₹85 each.
- **Approval mistakes:** Incorrect reasons or number of approvals.
- **Cost and speed:** How much each invoice costs and how long processing takes.
- **Processing failures:** Whether any invoice gets skipped.

I focused on missed reviews because they could lead to incorrect payments.

## Starter versus mine, on the same model

Both versions used Claude Opus 5.5.

| Metric | Starter* | Mine |
|---|---:|---:|
| Missed reviews | 2 | 0 |
| Unnecessary reviews | 1 | 0 |
| Cost per document | ₹13.55 | ₹1.77 |
| Latency p50 | 39.6 sec | 7.2 sec |
| Latency p95 | 46.1 sec | 11.9 sec |
| Field accuracy | 99.7% | 99.3% |

*The starter column uses the JSON-reading diagnostic fix. The unchanged starter produced no usable predictions. My corrected Opus results were checked using saved model responses.*

The two missed duplicates, `dev_015` and `dev_019`, represented **₹1,06,495 in potential duplicate-payment exposure**. No money was actually paid.

### My final version

I switched to Haiku for normal extraction and used Opus only when needed.

| Metric | Final result |
|---|---:|
| Missed reviews | 0 of 13 |
| Unnecessary reviews | 0 of 11 |
| Field accuracy | 99.7% |
| Cost per document | ₹0.11 |
| Latency p50 / p95 | 3.9 / 5.3 sec |
| Model escalations | 1 of 30 |

These results meet the cost and speed targets on this small sample. The final numbers include saved-response testing, not a fresh complete run.

## Labels I disagree with

For `dev_015`, the expected invoice number has no spaces, but the document prints spaces around the separators.

I believe the extracted value should match the printed document. If that interpretation is accepted, the final field accuracy becomes **100%**. The duplicate-payment decision does not change.

## Failure analysis

I found three main problems:

1. **Missing payment checks:** The starter missed duplicates because it wasn't using payment history properly. I moved these decisions into Python.
2. **JSON errors:** The starter couldn't handle some model responses. I fixed the response-reading logic.
3. **Different number formats:** The models sometimes returned values like `12 BOX` or `100819/-`. I improved the parsing rules.

One USD invoice still needs a second model call because of its amount format.

## How much to trust these numbers

The results are promising, but the dataset is small.

Only 24 invoices have development labels, and 13 need review. In real operations, Meridian expects only about 13% to need review.

I tested each configuration once and improved some rules after looking at the test documents. I also haven't tested enough real OCR documents, emails, e-invoices or busy production days.

So, **zero missed reviews here does not guarantee zero mistakes in production**.

## My recommendation

**Yes, with conditions.**

I would let Meridian use Ledgerline for invoice extraction and checks in a **two-week trial**, but keep payment approvals in the existing AP process.

Before using it for real approvals, I would require proper login, user roles, HTTPS and more testing. The current system already blocks production approvals because authentication is missing.

I would also monitor missed reviews, unnecessary reviews, processing errors and AI costs. Finance should approve the two optional policy checks before enabling them.

If the trial misses an important duplicate, bank change or invalid GSTIN, I would delay the rollout.

**Overall, Ledgerline is safer and cheaper than the starter, but it still needs real-world testing and stronger security before handling production payments.**
