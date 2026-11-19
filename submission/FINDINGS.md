# Findings

## The three fixes I would ship first, and why

1. **Stop duplicate payments.** I was able to reproduce multiple payment instructions for the same invoice. This is the first thing I would fix because it can directly lead to financial loss.
2. **Let code make payment decisions, not the AI model.** The original system missed two duplicate invoices in the development set. I want Python to check the policy and payment history every time.
3. **Protect bank information.** The original prompts exposed full bank account numbers to the AI provider. Those details should stay inside Meridian's system.

## My top eight, ranked by business risk

### F1: One invoice could create multiple payments

- **Severity:** Critical
- **Why it ranks here:** This could directly cause Meridian to pay the same invoice more than once.
- **Where:** `approve_invoice` and `reject_invoice` in `backend/ledgerline/api.py`, and the payment and approval tables in `backend/ledgerline/db.py` (`_add_unique_indexes`).
- **What's wrong:** The original approval process did not safely handle repeated clicks or simultaneous requests.
- **Impact:** A duplicate payment could be created without anyone intending to pay twice.
- **How I found it:** I used Claude Code to test repeated and simultaneous approval requests against SQLite.
- **Evidence from my run:** I used a test invoice (₹23,458) uploaded through the real API, with the starter's payment logic unchanged. Before the fix, a double-click created 2 payment instructions. Eight simultaneous requests created 8 (`submission/evidence/fix4_repro_before.txt`).
- **What it could cost Meridian:** For an invoice worth an assumed ₹40,000, one duplicate payment could put another ₹40,000 at risk. At 30 affected invoices per month, that would be ₹12 lakh of potential exposure. This is an illustration, not an actual loss.
- **Fix:** Added database constraints, transactions and checks against repeated payments. Commit `53e4fb4`.
- **Regression test:** `test_approvals.py::test_double_click_records_one_approval_and_one_payment`, `test_approvals.py::test_concurrent_approvals_create_exactly_one_payment`, `test_approvals.py::test_another_approver_on_an_approved_invoice_creates_no_second_payment` and `test_approvals.py::test_the_database_itself_refuses_a_second_payment_instruction`.
- **Status:** Fixed and tested locally.

### F2: The AI missed duplicate invoices

- **Severity:** Critical
- **Why it ranks here:** Even if the payment button works correctly, an invoice marked READY incorrectly could still be paid.
- **Where:** `process_document` in `backend/ledgerline/pipeline.py`, which took the routing from the model's answer, and `check_duplicate` in `backend/ledgerline/validation.py`.
- **What's wrong:** The AI was making routing decisions without checking all the information required by the AP policy, especially payment history.
- **Impact:** Two duplicate invoices were treated as ready when they should have gone to review.
- **How I found it:** I compared the starter's results against the labelled development invoices using the evaluation script.
- **Evidence from my run:** The unchanged starter skipped its predictions because of JSON errors. After adding a diagnostic JSON-reading fix, `dev_015` and `dev_019` were incorrectly marked READY.
- **What it could cost Meridian:** The two invoices represented **₹1,06,495 in potential duplicate-payment exposure**. No actual money was paid.
- **Fix:** Moved policy checks and routing decisions into Python. Commit `5b8bea3`.
- **Regression test:** `test_routing_duplicates.py::test_dev_015_resubmitted_paid_invoice_is_a_duplicate` (already paid), `test_routing_duplicates.py::test_dev_019_emailed_copy_of_dev_006_in_the_same_batch_is_a_duplicate` (same batch) and `test_routing_duplicates.py::test_model_cannot_route_a_paid_duplicate_as_ready`.
- **Status:** Fixed. Both invoices now go to review.

### F3: Full bank account numbers were sent to the AI

- **Severity:** High
- **Why it ranks here:** Bank details are sensitive, and the AP policy limits what can be shared with external models.
- **Where:** `build_extraction_prompt` and `build_verification_prompt` in `backend/ledgerline/extraction.py`. Both included the full vendor master (`vendors.csv`), and the extraction prompt also included three example documents.
- **What's wrong:** Full bank account numbers were included in the information sent to Anthropic instead of being masked.
- **Impact:** Sensitive financial details left Meridian's system unnecessarily.
- **How I found it:** I inspected the starter's model requests with Claude Code and checked what information was actually being transmitted.
- **Evidence from my run:** The original request included 37 full account numbers (`submission/evidence/fix5_6_tests_before.txt`). The starter's second, verification call sent the same vendor information again.
- **What it could cost Meridian:** No financial loss was observed. The cost of a privacy incident cannot be measured from this test. As a limited illustration, manually reviewing 100 affected records at ₹85 each would cost ₹8,500, excluding any investigation or legal costs.
- **Fix:** Mask bank details before model calls and handle the full details locally. The masking is in `tokenize_for_llm` and the local reading in `find_bank_details` (`backend/ledgerline/bank.py`). The vendor master, examples and verification call are no longer sent. Commit `2b24b53`.
- **Regression test:** `test_privacy.py::test_no_full_account_number_is_sent_to_the_llm` (all 30 documents), `test_privacy.py::test_no_long_number_survives_masking_whatever_its_label`, `test_privacy.py::test_the_vendor_master_is_not_sent` and `test_privacy.py::test_neither_the_primary_nor_the_escalation_model_sees_a_misleadingly_labelled_account`.
- **Status:** Fixed for outbound model requests. Local database encryption is still missing.

### F4: The system did not verify who was approving invoices

- **Severity:** Critical
- **Why it ranks here:** Payment approvals should only be made by authorized employees.
- **Where:** `backend/ledgerline/api.py` and the approval endpoints.
- **What's wrong:** The original API trusted the user ID and organization supplied by the browser. It had no real login or role checks.
- **Impact:** Someone with API access could claim another person's identity and attempt to approve payments.
- **How I found it:** I reviewed the API behavior with Claude Code and verified that approval requests succeeded without authenticated identities.
- **Evidence:** Before the safeguard, 18 security regression cases failed because requests that should have been blocked were accepted (`submission/evidence/approval_safeguard_tests_before.txt`).
- **Fix:** Added a safeguard that blocks approval and rejection outside local development (`backend/ledgerline/safeguard.py`). Commit `7f2198b`.
- **Regression test:** `test_approval_safeguard.py`, with 18 failing cases before the fix and 20 passing cases afterward.
- **Status:** Partly fixed. Unsafe production approvals are blocked, but proper authentication and role-based authorization are not implemented.

### F5: Important approval rules were not enforced properly

- **Severity:** High
- **Why it ranks here:** The policy requires different approval rules depending on the invoice, and some invoices must never be approved for payment.
- **Where:** `approve_invoice` and `_distinct_approvers` in `backend/ledgerline/api.py`, and `required_approvals` in `backend/ledgerline/validation.py`.
- **What's wrong:** The original system did not reliably enforce rules for duplicate invoices, credit notes and distinct approvers.
- **Impact:** A credit note or duplicate could reach payment, or the same person could be counted more than once.
- **How I found it:** I reproduced approval problems against the database and compared the results with `AP_POLICY.md`.
- **Fix:** Added approval restrictions, distinct-approver checks and database protection. Credit notes and distinct approvers are in commit `53e4fb4`. Blocking duplicates from approval is in commit `5b8bea3`.
- **Regression test:** `test_approvals.py::test_a_credit_note_cannot_be_approved_or_paid`, `test_routing_duplicates.py::test_a_duplicate_cannot_be_approved`, `test_approvals.py::test_one_person_approving_twice_counts_once`, `test_approvals.py::test_the_database_itself_refuses_the_same_approver_twice` and `test_routing_duplicates.py::test_required_approvals_follow_the_policy`.
- **Status:** Fixed for the implemented approval logic. Verified user identities are still required before production use.

### F6: Invoice text could become unsafe HTML in the review screen

- **Severity:** High
- **Why it ranks here:** Reviewers should not be exposed to executable content from untrusted invoice text.
- **Where:** `frontend/src/App.tsx` and the notes display.
- **What's wrong:** The original UI displayed model-generated notes as raw HTML. A malicious invoice could cause unsafe HTML to appear in the reviewer's browser.
- **Impact:** A successful browser script injection could affect a reviewer session.
- **How I found it:** Claude Code reproduced the problem using the actual attack-containing `dev_013` document and a frontend regression test.
- **Fix:** Added `NotesCallout.tsx` to display notes as plain text instead of HTML.
- **Regression test:** `NotesCallout.test.tsx`, with 2 failing safety checks before the fix and all 4 tests passing afterward.
- **Status:** Fixed in commit `2d0ecf2`.

### F7: The starter could skip invoices when the model response was not valid JSON

- **Severity:** High
- **Why it ranks here:** An invoice should never disappear from processing just because an AI response has the wrong format.
- **Where:** `parse_model_json` in `backend/ledgerline/extraction.py`, `predict` in `backend/ledgerline/cli.py` (the starter printed `[skip]` and moved on), and `backend/eval/run_eval.py` (it crashed with a division by zero when nothing was predicted).
- **What's wrong:** The starter expected plain JSON. When Opus returned JSON inside Markdown fences, parsing failed and the system skipped the document.
- **Impact:** Invoices could go unprocessed without a proper error record.
- **How I found it:** The original evaluation run produced no valid predictions for the 24 development invoices.
- **Fix:** Added more reliable response parsing and a `processing_error` output when processing fails. Commit `07c2472`.
- **Regression test:** `test_processing_errors.py::test_recorded_opus_response_with_fence_and_prose_is_parsed`, `test_processing_errors.py::test_batch_never_skips_a_document`, `test_processing_errors.py::test_unparseable_response_goes_to_review_as_processing_error` and `test_processing_errors.py::test_unresolved_processing_error_never_creates_a_payment`.
- **Status:** Fixed. In the clean-clone check, the full test suite passed, including `test_processing_errors.py::test_batch_does_not_skip_a_file_that_is_not_valid_utf8`, which confirms that an unreadable input creates an error record instead of being skipped.

### F8: The reported AI cost was incorrect

- **Severity:** Medium
- **Why it ranks here:** Finance and engineering need reliable costs before deciding whether the system is affordable.
- **Where:** `USD_PER_MTOK` and `cost_usd` in `backend/ledgerline/llm/pricing.py`, which feed the `/api/stats` cost dashboard.
- **What's wrong:** The price table treated per-million-token prices incorrectly, making the dashboard report costs about 1,000 times too low.
- **Impact:** Meridian could make rollout decisions using misleading cost figures.
- **How I found it:** I compared the recorded API usage with Anthropic's model prices and the dashboard calculation.
- **Fix:** Corrected the pricing calculation and tested a lower-cost model with fallback. Unknown models are now reported as unpriced, not free. Commit `2b24b53`.
- **Regression test:** `test_cost_reporting.py::test_prices_are_usd_per_million_tokens`, `test_cost_reporting.py::test_recorded_baseline_usage_reproduces_what_was_billed`, `test_cost_reporting.py::test_the_dashboard_reports_the_real_cost` and `test_cost_reporting.py::test_an_unknown_model_is_reported_as_unpriced_not_free`.
- **Status:** Fixed in the application's pricing code. The final sample estimated ₹0.11 per document, although fresh production measurements are still needed.

## Everything else I found (one line each)

- The reported 94.2% field accuracy did not measure whether payment-routing decisions were correct.
- The original prompt included development examples and their answers, which made the evaluation partly leaked.
- Reviewers still cannot click a value to see exactly where it came from in the original document.
- The supplier bank-change call-back process has not been implemented.
- The Approve button's original slowness could not be reproduced locally.
- The original AP policy does not check quantity × unit price for every invoice line.
- The policy does not explicitly handle invoices dated later than their email or processing date.

## Found but not fixed

- **Authentication and roles:** There is no verified login or role-based authorization. Production approvals are blocked as a temporary safeguard.
- **Database encryption:** SQLite still stores invoice data and bank details without encryption.
- **Transport security:** The local API uses HTTP. Production deployment would require HTTPS.
- **CORS:** The development configuration allows requests from any origin.
- **Evidence view:** Reviewers cannot yet trace each extracted field back to its source.
- **Bank-change verification:** A complete supplier call-back and approval workflow is still missing.
- **Other security checks:** CSRF, rate limiting, upload-size limits, audit-log tamper resistance and dependency security have not been fully tested.
- **Production-scale testing:** I have not tested real production traffic, changing invoice layouts or month-end load.

## Things I'm not sure are problems at all

- **Notes addressed to automation:** Some suppliers may simply want an invoice number included in the payment reference. The policy currently flags these notes, but not every such message is an attack.
- **Future-dated invoices:** The date difference in `disp_06` is unusual, but the email header is not reliable proof of receipt. It might be an innocent error.
- **Foreign currency from Indian suppliers:** An Indian supplier billing in USD is not necessarily doing anything wrong. The policy needs clearer handling of these cases.
- **Extra reviews from new checks:** Line-arithmetic and date checks improve safety, but they could also increase unnecessary reviews. I would measure that before enabling them in production.
