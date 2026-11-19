# Evaluation report

## Setup

- **Provider:** Anthropic API. **Models:** Claude Opus 5.5 (`claude-opus-5-5`, the starter's production model) and
  Claude Haiku 5.5 (`claude-haiku-5-5`). List prices checked 18 Nov 2026: Opus $4 / $20, Haiku $0.10 / $0.50 per
  million input / output tokens; ₹88 per USD (the starter's planning rate).
- **Runs:** 18 Nov 2026, real API calls, some re-read later through newer code from their recorded responses (see
  "Where each number comes from"). No number is estimated from token counts I did not observe. Spend: **$5.30**
  recorded by the evaluation recorder, plus about $0.16 for two early smoke-test calls.
- **Documents:** the 24 labelled dev documents and the 6 unlabelled disputed documents.
- **Reproduce** (from `backend/`; each run folder in `submission/baseline/` has a `CODE_VERSION.txt`):

  ```bash
  python eval/baseline_starter.py --mode improved --model claude-opus-5-5
  python eval/baseline_starter.py --mode improved --model claude-haiku-5-5 --escalation-model claude-opus-5-5
  python eval/score_predictions.py .. ../submission/baseline/<run>/<folder>/predictions_dev.jsonl
  python eval/check_contract.py ../data/invoices/dev ../submission/predictions_dev.jsonl
  ```

  Raw model responses are cached locally (git-ignored), so re-scoring after a code change costs nothing as long as
  the prompt is unchanged.

### The four pipelines compared, and the code each ran

| Name | What it is | Code | Model |
|---|---|---|---|
| **Unchanged starter** | The starter exactly as handed over | starter (`6e59f77`) | Opus 5.5 |
| **Diagnostic starter** | The starter plus a shim that only cuts the JSON out of the model's reply (a verbatim slice, nothing else changed), so its *logic* can be measured. **Not** the original baseline. | starter + shim | Opus 5.5 |
| **Earlier improved (Opus)** | My pipeline: code decides routing, masked prompt, one call per document | `2b24b53` | Opus 5.5 |
| **Final pipeline** | My pipeline after the quantity, amount-format and escalation fixes; Haiku first, Opus only when Haiku cannot produce a usable extraction | `64a7d51` | Haiku 5.5 → Opus 5.5 |

### Where each number comes from

Three kinds of number appear in this report, and they are not equally strong:

- **Real calls**: measured on a live provider call made by that pipeline's own code.
- **Cached replay**: the *same recorded model responses* run through *later code*, with no new calls. The prompt was
  identical, so the model's output is what it would have been; only the code that reads it differs. Cost and token
  counts are the recorded ones.
- **Reconstructed latency**: a document's latency added up from recorded calls that were not all made in the same run.

| Pipeline | Calls | Code that read the responses | Kind |
|---|---|---|---|
| Unchanged starter (run A) | 30 Opus calls, run A | starter | **real calls** |
| Diagnostic starter (run B) | 2nd call of each document real in run B; 1st call reused from run A (same prompt) | starter + shim | **real calls**; per-document latency **reconstructed** from A and B |
| Earlier improved, as run | 30 Opus calls at `2b24b53` | `2b24b53` | **real calls** |
| Earlier improved, re-scored (99.3%, 0 unnecessary) | the same 30 responses | `6bf339b` | **cached replay** |
| Final pipeline: Haiku reads | 30 Haiku calls at `4b6a0d3` | `64a7d51` | **cached replay** of real calls; Haiku latency real |
| Final pipeline: the one escalation (dev_014) | the Opus response for this exact prompt, recorded in the earlier Opus run | `64a7d51` | **cached replay**; that document's latency **reconstructed** (its Haiku call + the recorded Opus call) |
| Escalations 5 → 1 | the paid Haiku run escalated 5 at `4b6a0d3`; the 1 is the same responses through `64a7d51` | | **cached replay** |

So the final pipeline's routing, cost and latency are the real responses and real recorded latencies, read by the
final code. They are not a fresh end-to-end run of `64a7d51`; that would cost about $0.05 and was not done.

## What the "94%" actually measured

- **What it is:** `eval/run_eval.py`, exact match on 12 header fields (type, supplier, GSTIN, number, date,
  currency, subtotal, the three taxes, total, PO). It does **not** score routing, review reasons, approvals, bank
  details or line items, which are what move money.
- **Reproduced on my model:** **it cannot be.** On Opus 5.5 the unchanged starter wrote 0 of 24 predictions (every
  reply was fenced JSON and `json.loads` raised; every document was skipped) and `run_eval.py` crashed with
  `ZeroDivisionError`. Counting failed documents as failures, the starter scores **0/288 = 0%**.
- **The diagnostic starter** (same responses, JSON cut out) scores **99.7%** by run_eval's method. That is higher
  than 94.2%, so the handover's number probably came from a different model or prompt version; I cannot recover it.
- **Re-scored with leaked examples removed:** the first three dev documents (dev_001 to dev_003) are pasted into
  every starter prompt with their expected answers. Removing them from the *score*: 99.7% → **99.6%**. This removes
  them from the denominator only: the examples were still in every prompt and shaped the model's output format for
  all 24 documents. A truly leak-free starter number needs a re-run with the examples removed from the prompt; I did
  not pay for that (~$4.70) and report it as a limitation. My pipeline sends no example documents, so its numbers
  are leak-free by construction.
- **Failed documents counted as failures:** run_eval silently drops a document that raises, so a system that crashes
  on 23 of 24 documents could still report 100%. With failures counted: unchanged starter 0%; diagnostic starter
  99.7% (no failures).
- **Conclusion:** the 94% was a field-accuracy number on a partly leaked sample, blind to the errors that matter. The
  diagnostic starter's 99.7% field accuracy sits next to **2 missed reviews out of 13**, both duplicates that would
  have been payable a second time.

## What I chose to measure, and why

1. **Missed reviews** (labelled needs review, routed ready): a missed review can mean paying a fraudster or paying
   twice. The AP Lead: "I can't live with a missed one." This is the headline.
2. **Unnecessary reviews** (labelled clean, routed to review): each costs ~₹85 of AP time and can delay an MSME
   payment (the Finance Controller's concern).
3. **Reason and approval-count errors:** a document routed to review for the wrong reason wastes the reviewer's time;
   a wrong approval count breaks section 4.
4. **Documents skipped or failed** (`processing_error`): never allowed to be skipped; failures must be visible.
5. **Cost per document (₹) and latency p50 / p95 per document**, measured from real calls, against the CTO's targets
   of ₹1.50 and 10 s.
6. **Field accuracy**, run_eval's method, only for comparison with the handover.
7. **Escalations** (how many, why), because they drive cost and tail latency.

## Starter versus mine, on the same model

Dev set (24 labelled documents), both on Claude Opus 5.5.

| Metric | Starter | Mine |
|---|---|---|
| Missed reviews (needed review, predicted ready; of 13) | **2** (dev_015, dev_019: ₹1,06,495 potential duplicate-payment exposure) | **0** |
| Cost per document (₹) | **13.55** | **1.77** |
| Latency p50 and p95 (seconds) | **39.6 / 46.1** | **7.2 / 11.9** |
| Unnecessary reviews (labelled clean, routed to review; of 11) | 1 (dev_016) | 0 |
| Documents with a wrong review reason or approval count | 6 | 0 |
| Field accuracy (run_eval's method) | 99.7% | 99.3% |
| LLM calls per document | 2 | 1 |

- **"Starter"** is the diagnostic starter: the starter plus a shim that only cuts the JSON out of the reply. The
  unchanged starter cannot fill this column: it wrote **0 of 24** predictions (every document skipped), cost ₹6.62 a
  document for nothing and crashed the evaluation.
- **"Mine"** is my pipeline's routing code read over the real Opus responses from the paid run at `2b24b53`, re-read
  through `6bf339b` after the quantity fix (cached replay, no new calls). Cost and latency are those real calls.
- **On Opus alone, my pipeline still misses both CTO targets** (₹1.77 > ₹1.50; 11.9 s > 10 s): output tokens are 77%
  of Opus's cost. That is why the final pipeline uses Haiku first.

### All four pipelines, including the final one

| Metric | Unchanged starter | Diagnostic starter | Earlier improved (Opus) | **Final pipeline** |
|---|---|---|---|---|
| Predictions written | **0 / 24** (all skipped) | 24 / 24 | 24 / 24 | **24 / 24** |
| **Missed reviews** (of 13) | n/a: nothing routed | **2** (dev_015, dev_019: ₹1,06,495 potential duplicate-payment exposure) | 0 | **0** |
| Unnecessary reviews (of 11) | n/a | 1 (dev_016) | 3 (quantity bug) | **0** |
| Reason or approval-count differences | n/a | 6 documents | 5 documents | **0** |
| `processing_error` | (skipped instead) | 0 | 7 | **0** |
| Field accuracy (run_eval) | crash (0% counting failures) | 99.7% | 80.9% | **99.7%** |
| **Cost per document (₹)** | 6.62 (one call, then crash) | **13.55** | 1.77 | **0.11** |
| **Latency p50 / p95 (s)** | 18.2 / 20.0 (one call) | **39.6 / 46.1** | 7.2 / 11.9 | **3.9 / 5.3** (30 docs) |
| LLM calls per document | 1 (crashes) | 2 | 1 | 1.04 (1 escalation in 30) |

The "Earlier improved (Opus)" column is that run *as it ran* at `2b24b53`, before the quantity fix; the same-model
table above shows the same responses re-read by the fixed code.

**Final pipeline, against the targets:** ₹0.11 per document (max ₹1.95, the one escalated document) and p95 5.3 s
over the 30 documents: **both targets met on this sample.** Without escalation a document costs ~₹0.05 and takes
3.8 s at the median (5.3 s at most); the escalated one cost ~₹1.95 and took ~13 s. The p95 stays under 10 s only while fewer than 5% of documents
escalate (here 1 in 30, 3%).

**Escalations.** In the paid Haiku run, the earlier rule escalated 5 of 30 documents: three for deterministic policy
failures (dev_008 `totals_mismatch`, dev_010 and disp_01 `gstin_invalid`), which a second reading is not allowed to
clear, so escalation only added ~₹1.90 and ~8 s each; and two because Haiku copied amounts as printed (`100819/-`,
`$50.00`). I stopped escalating on policy failures and taught the amount parser the formats AP_POLICY section 1
lists (`Rs.`, `/-`), still refusing anything else. The final pipeline escalates **1 of 30** (dev_014: `$50.00`, a USD
invoice), and its routing is unchanged.

**Disputed set (flags on, final pipeline):** all six match my rulings (RULINGS.md): disp_01 `gstin_invalid` +
`vendor_unknown`; disp_02 `duplicate`; disp_03 `foreign_currency`, 2 approvals; disp_04 `suspicious_content`;
disp_05 `line_amount_mismatch`; disp_06 `future_dated`. With both flags on, no dev document changes.

**The CTO's bill.** The dashboard's ₹15 is the bill divided by 1,000 ($165 × 88 / 1,000 ≈ ₹14.5): the price table
held per-thousand prices under a per-million label. $165 for ~2,400 documents is ~$0.069 a document, close to one
Opus call ($0.076), not two; that fits documents failing after the first call, as they did for me. That last part is
a hypothesis to check against the bill's daily breakdown.

## Labels I disagree with

- **dev_015 `invoice_number`.** The label is `SIS/26-27/0018`; the document prints `SIS / 26-27 / 0018`, and the
  contract asks for the number "as printed". If I'm right, field accuracy is 288/288 for the final pipeline. Routing
  is unaffected: the duplicate rule compares *normalised* numbers.
- No routing labels: they follow the written policy literally, and my departures from it are behind flags that are
  off for the dev predictions.

## Failure analysis

- **Extraction format drift** (the most important lesson): removing the starter's example documents from the prompt
  changed how the model formats values. Opus returned quantities with units (`12 BOX`), Haiku returned amounts as
  printed (`100819/-`). Each was caught by the evaluation on real responses, not by unit tests, and fixed in code
  (quantity read leniently; amounts in the policy's listed formats only; money otherwise strict).
- **Rules, not the model, caused every missed review in the starter:** the model was never given the payment history
  it needed for the duplicate rule. With code deciding routing, the same Opus answers produce 0 missed reviews.
- **Currencies other than INR:** a USD amount (`$50.00`) is not a format the policy lists, so it escalates; it is a
  small cost (one Opus call per USD invoice), not a routing risk.
- **What I did not test:** real OCR noise beyond these 30 documents; new layouts the local bank-detail reader does not
  recognise (they go to review as unverified, which is safe but costs ₹85 each); concurrent production load.

## How much to trust these numbers

- **The sample is small and deliberately hard.** 24 labelled documents, 13 needing review (54%), against 13% in
  production. One document is ~4 percentage points. "0 missed reviews" means "none in 13", not "none in 3,000".
- **One run per configuration.** I did not measure run-to-run variation; Haiku's and Opus's formatting varied between
  models, so it will vary between runs too. The code is designed to fail safe when it does (`processing_error` or
  escalation, never an invented value).
- **Latency of the escalated document** is the recorded latency of a real Opus call made during the earlier Opus run
  (the prompt was identical, so the Haiku run reused the cached response). It is a real measurement, but not one taken
  under the final run's network conditions.
- **I tuned some checks while reading this data** (the `suspicious_content` patterns after reading dev_012, dev_013
  and disp_04), so the perfect dev score partly measures my reading of these documents.
- **Not covered:** the production mix (70% OCR, 20% email, 10% e-invoice) at volume; month-end peaks of 400 a day;
  vendors and layouts not in the sample.

## My recommendation

**Yes, with conditions.** Route every invoice through Ledgerline next month for extraction and checks, but **keep
payment approvals out of Ledgerline in production**: approvals stay in Meridian's current process until the security
controls below exist, and there is no automatic approval (AP_POLICY 4.3). Specifically:

1. **Payment approvals in Ledgerline must remain disabled in production until authentication and role-based
   authorization are in place.** Today the approver's identity and organisation are whatever the browser sends and
   any caller can approve, so "two approvers" proves two names, not two people (FINDINGS F4). Required
   first: identity and roles taken from Meridian's SSO on the server, approval limited to the AP Lead and Finance
   Controller, TLS in front of the API, and CORS restricted to Meridian's own UI. This is **enforced in code**, not
   just recommended: approve and reject return 403 everywhere except local development (`LEDGERLINE_ENV=development`
   and a request from the same machine); an unset environment counts as production, and no setting enables approvals
   there (`backend/ledgerline/safeguard.py`, 20 tests in `test_approval_safeguard.py`). Its limit: behind a reverse
   proxy on the same host every caller looks local, so `development` must never be set on a server.
2. **Run two weeks in shadow mode first** on real November documents, with the AP team's own decisions as the label.
   Use Ledgerline's routing only if there are **zero missed reviews** on duplicates, bank changes and invalid GSTINs,
   and the unnecessary-review rate is within ~5 points of the AP team's own review rate.
3. **Watch three numbers daily:** the escalation rate (p95 stays under 10 s only below ~5%), the `processing_error`
   rate, and the provider bill against the dashboard.
4. **Finance Controller to decide on the two flags** (line arithmetic, future-dated invoices) before they go live.

**How the recommendation weighs the two errors.** An unnecessary review costs ~₹85 (CFO). A missed review can cost
the whole invoice. Invoice values are an **illustrative assumption** (I have no production distribution; 40% are
under ₹10,000, and the dev median is ₹41,036): one prevented wrong payment of ₹10,000 pays for ~118 unnecessary
reviews, one of ₹40,000 for ~470, one of ₹75,000 for ~880. On the review side, from Meridian's own figures: at 3,000
documents a month, sending 20% to review (well above the 13% that genuinely need it) costs ~₹51,000 of AP time,
against ~₹2.55 lakh to handle everything by hand. **Measured:** the starter routed two duplicates as ready on 24 dev documents, ₹1,06,495 of
potential duplicate-payment exposure (not money actually paid). LLM cost at ₹0.11 a document is ~₹340 a month and is not the deciding factor.

**What would change my mind:** any missed duplicate, bank change or invalid GSTIN in the shadow run; an escalation or
`processing_error` rate above ~5% on real documents (cost and p95 would follow); or reviewers still re-keying
invoices because they cannot see where values came from (the evidence view is not built yet).
