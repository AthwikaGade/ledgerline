# Decisions

## Architecture

**What the model does, what code does.** The model only reads the document and returns its fields as JSON. Code
decides everything that moves money: every review reason in AP_POLICY section 3, the number of approvals in
section 4.1, duplicate detection, bank-detail checks, and whether an invoice can be approved at all. The model's own
opinion on routing, if it gives one, is stored as an advisory note for the reviewer and never used. This restores
the original design's rule ("the LLM only extracts; code decides", ARCHITECTURE.md), which the handover had reversed.
It is what makes the routing testable: 349 offline backend tests (plus 4 frontend tests), including
recorded model responses.

**Prompt and output.** One call per document. The prompt holds a short field list and the document, nothing else:
no policy text, no vendor master, no example documents (they leaked dev labels into the evaluation and carried full
account numbers). The reply is parsed as a verbatim slice of JSON (bare, fenced or inside prose). Values are read
strictly: money only in the formats AP_POLICY 1 lists, dates according to the vendor's country; only quantity is
read leniently. A missing critical field, an unreadable value or an unrestorable masked number is a
`processing_error`: the document goes to review, nothing is invented, and it can never be approved until it is
re-extracted.

**Hostile documents.** The document is treated as data: the system prompt says never to follow instructions inside
it, and in any case the model's routing opinion is ignored, so a document "telling the AI" to mark it ready has no
effect on routing. Text addressed to automated systems and embedded markup are flagged deterministically
(`suspicious_content`, dev_012 and dev_013). Bank details are read locally from the original document, so a model
that misreads or is manipulated cannot vouch for an account.

**What leaves Meridian's systems.** Only the masked document text. Every run of 9 or more digits, whatever its
label, is replaced by a numbered token that keeps the last four digits; the originals are restored locally from the
tokens. No vendor master, no payment history, no policy text and no other document is sent. Tested on all 30
documents for both the primary and the escalation model, including unknown account numbers under misleading labels.

**Money and approvals.** Every approval or rejection runs in one SQLite transaction; unique indexes make the
database itself refuse a second payment instruction for an invoice or the same approver twice; every decision is in
an audit log. Unchanged: no new database, queue or vendor (the CTO's constraint).

## Part 4: what I went deep on, and why

**Option B: survive production.** I chose it because the evaluation showed the starter could not run at all on the
current model (every reply wrapped in a code fence, every document skipped) and cost ₹13.55 per document with a
46-second p95, against targets of ₹1.50 and 10 seconds. A reviewer screen (option A) matters only once the pipeline
runs reliably within budget, and building one well (character offsets, a queue, double-click safety for 150
invoices a day) was more than the time left after the payment-safety fixes. The approval part of option A
(server-side rules, safe under double-clicks and retries) was done anyway as FINDINGS F1 and F5. I did not choose option C:
nothing I could argue mattered more to Meridian next month than not paying twice and running within budget.

What I built and measured:

- **The cheapest model that is good enough:** Haiku 5.5 as the primary. With the same prompt, its responses give the
  same dev-set routing as Opus's (0 missed, 0 unnecessary reviews, no reason or approval differences, both read by the
  final code) at ₹0.11 per document, against ₹1.77 measured for Opus.
- **Escalation when the cheap model fails:** if the primary call fails, the reply is unusable, a critical field is
  missing or a value is unreadable, the document goes to the escalation model (Opus). Escalation never overrides a
  deterministic review reason, and since the paid run it no longer triggers on them, because a second reading could
  not change the decision: that cut escalations from 5 to 1 in 30.
- **Provider outage:** the escalation model can be on a different provider (`LLM_ESCALATION_PROVIDER`), so a failed
  primary call falls back to it; if both fail the document becomes a `processing_error`, never a dropped line.
- **Within budget:** the cost and quality trade-off, from real calls (some re-read later from their saved responses), is in EVAL_REPORT: ₹0.11 per document,
  p50 3.9 s, p95 5.3 s on these 30 documents. The tail stays under 10 s only while fewer than ~5% of documents
  escalate.

What I did not build: a budget controller that switches models on spend, retries with backoff beyond the SDK's own,
and a measured outage drill against a second provider (it is tested only with simulated failures).

## Replies to stakeholders

### Anita Rao, CFO

I understand why you want smaller invoices approved automatically, but the current policy requires human approval for every payment. I wouldn't change that without Finance approving a new rule. I also wouldn't let AI automatically correct invalid GSTINs, because that could lead to payments being linked to the wrong supplier.

The final pipeline costs around ₹0.11 per document on our test sample, which is encouraging. For the board, I would focus more on preventing incorrect payments than just reducing AI costs. I recommend a controlled trial before making any rollout decision.

### Farhan Sheikh, Head of AP

I agree that reviewers should be able to see where invoice values came from. I haven't built the evidence-linked view yet, so that is still important follow-up work.

Bank details are now handled locally instead of sending full account numbers to the AI. Bank changes go to review, but I haven't implemented the supplier call-back process. I would work with AP to design that process before adding it.

I also tested a lower-cost model with a fallback to Opus. It gave the same routing results on our small development set, although we still need testing on real invoices.

### Deepak Menon, CTO

I found that the dashboard was using model prices incorrectly, making the reported cost about 1,000 times too low. I corrected the calculation.

I also reduced the number of model calls and tested Haiku with Opus as a fallback. The final sample shows around ₹0.11 per document and 5.3 seconds at p95, although the final results include cached replay and are not a fresh production benchmark.

I didn't add any new infrastructure or fine-tune a model. The biggest improvement came from letting Python handle the business rules instead of trusting the AI to make payment decisions.

### Priya Natarajan, Data Protection Officer

You were right to question what we send to the model. The original system included full bank account numbers in its prompts. I changed it so bank numbers are masked before anything is sent to Anthropic. I also added tests for different ways those numbers might appear.

However, the local SQLite database is still unencrypted, and the development API uses HTTP. Those are real security gaps. I would require encrypted storage, HTTPS, proper access controls and a security review before using this for production payments.

### Sunil Joshi, Finance Controller

I understand your concern about too many unnecessary reviews. Every extra review costs time and could delay supplier payments.

On the development set, the final pipeline had no unnecessary reviews, but 24 documents are not enough to prove it will perform the same way in production.

I kept the original AP policy unchanged. I proposed two optional checks for incorrect line calculations and future-dated invoices, both off by default. I would want your approval before enabling them. I also agree that the supplier call-back process should be designed properly before we add it.

### Ravi Kulkarni, contractor

I understand why you kept the policy in the prompt. It makes changes easier for Finance without needing a developer every time.

The problem is that an AI model shouldn't have the final say on payment rules, especially when invoice text might contain instructions trying to change its behavior. I moved those decisions into Python so they can be tested and give consistent results.

The trade-off is that changing a rule now needs a code update. A good next step could be keeping approved thresholds in a configuration file, while Python still validates and enforces them. That would give Finance more flexibility without making payment decisions depend on AI interpretation.

## Policy changes I propose

### 1. Check line arithmetic (disp_05)

- **What changes:** a new review reason when, on any line, quantity × rate differs from the printed amount by more
  than ₹1.00.
- **Why:** an overcharge on a single line is invisible to the existing totals rule, which only adds up the printed
  line amounts. disp_05 is ₹550 over on one line, ₹649 with GST.
- **What it costs or risks:** some extra reviews on lines with discounts or rounding. Implemented behind
  `LEDGERLINE_FLAG_LINE_ARITHMETIC`, off by default; switching it on changed no dev document.

### 2. Review future-dated invoices (disp_06)

- **What changes:** a new review reason when the printed invoice date is later than the date the document was sent
  (the email's Date header) or processed. The printed date stays the document date.
- **Why:** such a date cannot be right, and in disp_06 it also takes a new vendor out of the 90-day `vendor_new`
  check.
- **What it costs or risks:** the email's Date header is set by the sender, so it is only a consistency signal, not a
  verified receipt time. Implemented behind `LEDGERLINE_FLAG_FUTURE_DATED`, off by default; it changed no dev document.

### 3. Revised invoices that reuse a paid number (disp_02)

- **What changes:** such an invoice stays a duplicate that cannot be approved, and the vendor is asked for a separate
  adjustment document (debit note or supplementary invoice) for the difference. Written into section 3 or 4.4 so
  reviewers handle it the same way every time.
- **Why:** Ledgerline cannot "pay only the difference", and reusing a paid invoice's number is the double-payment
  pattern.
- **What it costs or risks:** extra paperwork for a vendor with a genuine price revision, and a delay to that payment.

### 4. Clarify notes addressed to automation (disp_04)

- **What changes:** section 3's `suspicious_content` says how to treat a note that only asks for something harmless
  (quoting an invoice number in a remittance) as opposed to instructions to skip checks or change a decision. Until
  the policy says how, Ledgerline keeps flagging both.
- **Why:** an honest vendor's routine note costs ₹85 of review each time and, if common, teaches reviewers to ignore
  the flag.
- **What it costs or risks:** a harmless-looking note is how a manipulation is tested first; any relaxation needs a
  human-maintained rule, not the model's judgement.

### 5. Show likely supplier matches for an invalid GSTIN, never correct it (disp_01)

- **What changes:** when a GSTIN fails its check, the reviewer is shown vendors whose GSTIN differs by one character
  (for disp_01, Sitara: `B` printed where the vendor master has `8`), with whether the bank details also match. The
  GSTIN is never changed automatically, and the document still goes to review.
- **Why:** it turns a slow re-key into a quick, informed decision, without giving up section 1's rule that a domestic
  supplier is identified by GSTIN alone.
- **What it costs or risks:** a near-match is exactly what a look-alike fraud would produce, so the suggestion must
  stay a hint to a human, never a correction.

### 6. Foreign-currency invoices from Indian suppliers (disp_03)

- **What changes:** section 1 says how to treat an invoice from a domestic supplier priced in another currency
  (disp_03: Narmada, Gujarat, USD with an INR equivalent for GST, paid by NEFT): which amount is paid, at what rate
  and on what date, and how many approvals it needs. Until then Ledgerline applies the policy as written: foreign,
  review, two approvals.
- **Why:** today the INR amount actually paid is not fixed by the invoice, so a reviewer has to decide it each time.
- **What it costs or risks:** treating such invoices as domestic would remove a review and an approval from routine
  suppliers, but would also remove the check on the exchange rate.

### 7. Authenticated approvers

- **What changes:** section 4.2 ("each approval must come from a different person") requires that approvers sign in
  through Meridian's SSO.
- **Why:** today the approver's name is whatever the browser sends, so two approvals prove two names, not two people.
- **What it costs or risks:** integration work with Meridian's identity provider before approvals move into Ledgerline.
