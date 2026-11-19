# Ledgerline: the Moring AI engineer challenge

Thanks for taking this on. This is the take-home for the **AI Engineer (full-stack)** role at Moring AI. It is modeled on work we do every week: taking an LLM workflow that "mostly works" and making it something a regulated enterprise can trust in production.

| | |
|---|---|
| **Time** | Plan for about 6 focused hours. Please stop at 8. Your deadline is in your invite email, usually 7 days away. |
| **AI tools** | Expected. Use Claude Code, Cursor, Copilot, ChatGPT: whatever you would use at work. |
| **Domain knowledge** | None needed to start. Learning it quickly is part of the job. Every written business rule is in [`docs/AP_POLICY.md`](docs/AP_POLICY.md). |
| **Stack** | Python 3.11+ (FastAPI, SQLite) and React with TypeScript (Vite). |

> **There is no single right answer.** Two strong engineers could hand in very different submissions. Where something is ambiguous, make a reasonable call and write down why.
>
> **Nobody finishes everything.** There is more here than 6 hours of work, on purpose. Choose what matters most, and say what you left out.

## How to submit

1. **Create your own repository from this one.** Sign in to GitHub, click the green **Use this template** button at the top of this page, then **Create a new repository**. Pick your own account as the owner, give it any name, and set it to **Public**. Please don't fork this repository.
2. **Do all your work in your new repository.** Clone it, work through the tasks below, and commit and push as you go.
3. **Send us your repository before your deadline.** Reply to your invite email with:
   - the link to your repository, for example `https://github.com/your-username/ledgerline`;
   - the ID of your final commit, which `git rev-parse HEAD` prints.

That commit is your submission, so don't push anything after you've sent it, and keep the repository public until you hear back from us. This repository is read-only: please don't open issues or pull requests here.

## The situation

Meridian Precision Components (fictional) is an auto-components manufacturer near Pune and a Moring client. Its accounts-payable (AP) team handles about 3,000 vendor documents a month: OCR text from scanned invoices, invoices typed into emails, and government e-invoice JSON.

Earlier this year a contractor built **Ledgerline**. It reads each document with an LLM, checks it against Meridian's AP policy, and routes it to *ready for approval* or *needs review*. He left at the end of October. Since then:

- the AP team says "the numbers are wrong sometimes", and one invoice was nearly paid twice;
- the CTO's LLM bill doesn't match Ledgerline's own cost dashboard;
- the handover note says accuracy is 94%.

Meridian wants Ledgerline handling every invoice next month. You have just inherited it.

## How we want you to work

Your AI tools can write most of the code in this repository. They can't decide what matters to a company that moves money through it, and they can't be accountable when a payment goes to a fraudster. That part is yours.

So use AI as much as you like, but make the decisions yourself, write them down in your own words, and be ready to explain each one. Where the code, the tests and the docs disagree, decide which to trust and say why. `docs/AP_POLICY.md` is the written policy and your default, but the people who own it are in [`docs/STAKEHOLDER_THREAD.md`](docs/STAKEHOLDER_THREAD.md), and they don't all agree with it. Where you think the policy is wrong, say so, and put any departure from it behind a flag (see Part 2).

## Your tasks

Every part is required in the sense that you must address it, even if only in a few honest lines. How deep you go in each one is your call. We would rather see two parts done properly and the rest addressed briefly and honestly than all seven done thinly. Say in `REFLECTION.md` what you cut, and why.

### Part 0: Your first hour (required, 30 to 45 minutes)

Before you change any code, read around and write [`submission/FIRST_HOUR.md`](submission/FIRST_HOUR.md): what you think is going on, the risks you suspect (most serious first), your plan for the time you have, and the questions you would ask Meridian.

Keep it under about 300 words. Commit it on its own, before any commit that touches `backend/` or `frontend/` (context files for your AI tools and your `.env` don't count), and **don't edit it afterwards**. Save the AI sessions from this stretch as their own file in `submission/ai-logs/`, with a name starting `00_first_hour`. It's fine if the note turns out to be wrong.

### Part 1: Make it trustworthy (required)

As it stands, Ledgerline should not be handling every invoice next month. Decide what "trustworthy" has to mean for Meridian, find out what stands in the way, and fix what you judge most important first. We won't tell you how many problems there are or which ones matter.

- Every fix gets a test that fails before the fix and passes after it. For a prompt or model-behaviour change, use a recorded model response as a test fixture, or show the change in your eval on named documents. For a UI fix, a test or a written manual check is fine.
- In [`submission/FINDINGS.md`](submission/FINDINGS.md), rank your top eight findings by business risk, in your own judgment, and explain the order. List the rest as one-liners. Include what you found but chose not to fix, and at least one thing you're not sure is a problem at all.
- For your top three, show evidence from your own run of the starter (the document, and what the starter actually produced for it) and estimate what the problem could cost Meridian in rupees.
- Prefer root causes to symptoms, and small, focused changes to rewrites.

### Part 2: Rule on the disputed documents (required)

[`data/invoices/disputed/`](data/invoices/disputed/) holds six documents that Meridian's own AP team argues about. They have no labels, and we don't have a right answer for them either. In [`submission/RULINGS.md`](submission/RULINGS.md), in about 150 words per document, give:

- your ruling: needs review or ready, with which reasons and how many approvals;
- the policy text your ruling rests on, or the gap in the policy it falls into;
- the strongest argument against your ruling, put as well as you can;
- the policy change you'd propose to the Finance Controller, if any;
- whether your own pipeline's line for it in `predictions_disputed.jsonl` matches your ruling, and if not, why.

Then make Ledgerline behave the way you ruled, at least for the two documents you consider riskiest, with tests.

Don't quietly change `AP_POLICY.md`. Where a ruling departs from the written policy, put the change behind a clearly named flag that is off by default and switched on with an environment variable (for example `LEDGERLINE_FLAG_<NAME>=1`). New review-reason codes are allowed only behind a flag. List your flags at the top of `RULINGS.md`, and produce `predictions_disputed.jsonl` with them switched on.

### Part 3: Measure, and make a call (required)

Build an evaluation you would be willing to defend to Meridian's CFO, and use it to make a recommendation in [`submission/EVAL_REPORT.md`](submission/EVAL_REPORT.md).

- Decide what to measure and why. At the very least we expect: how often a document that needed review was routed as ready; cost per document (₹) and latency (p50 and p95), measured from real calls; and the starter's numbers next to yours, on the same model. The rest is up to you.
- Explain what the handover note's "94%" actually measured. Reproduce the starter's number on your model, then re-score the starter with its leaked examples removed and failed documents counted as failures.
- The dev labels in `data/ground_truth/dev.jsonl` follow the written policy literally. If you disagree with any of them, say which and why, and show how it changes your numbers.
- The dev and disputed sets are deliberately rich in problem cases. For anything about Meridian's real volumes, use the production mix in [`docs/PRODUCT_BRIEF.md`](docs/PRODUCT_BRIEF.md).
- End with a recommendation: should Meridian put every invoice through Ledgerline next month? Yes, no, or yes with conditions. Say what evidence would change your mind. A missed review can mean paying a fraudster; an unnecessary review costs about ₹85 of AP time (see the CFO's email) and can delay a vendor's payment. Show how your recommendation weighs the two.

### Part 4: Go deep on one thing (required: choose one)

Choose one, and say in [`submission/DECISIONS.md`](submission/DECISIONS.md) why you chose it over the others.

- **A. Evidence-linked review.** Reviewers don't trust numbers they can't trace, so they re-key invoices by hand. Build the reviewer experience: for every extracted field, its exact source in the original document (character offsets plus the text; when you're not sure, say so rather than highlight the wrong text); a queue of documents that need attention; each review reason in plain language with the evidence behind it; and approve and reject actions that enforce the policy's approval rules **on the server** and stay correct under double-clicks and retries. It needs to work for a reviewer who clears 150 invoices a day.
- **B. Survive production.** Find the cheapest model that is good enough, escalate when validation fails, and keep working through a provider outage, within the CTO's budget. Show the cost and quality trade-off with numbers.
- **C. Your own idea.** Anything you can argue matters more to Meridian next month than A or B.

Whichever you choose, treat every document as hostile. Some in the dev set are.

### Part 5: Respond to stakeholders (required, written)

Read [`docs/STAKEHOLDER_THREAD.md`](docs/STAKEHOLDER_THREAD.md). In `submission/DECISIONS.md`, reply to each person in no more than about 120 words: what you did, what you won't do yet, and why. Use your own numbers where they help. Some requests conflict with each other or with the written policy, and at least one person argues against the approach you are most likely to take. Give that argument a real answer. Don't quietly change the policy; propose changes instead.

### Part 6: Reflect (required, about 20 minutes)

In [`submission/REFLECTION.md`](submission/REFLECTION.md): three things you didn't know when you started and do now, and how you learned each one; the decision you're least sure of, and what would show you it was wrong; and what you'd do with one more week, in order.

## Ground rules

- **AI tools are expected.** Save your sessions in `submission/ai-logs/` (Claude Code: `/export`; Cursor: export the chat; chat apps: share links or copied text). Redact secrets. Commit any context files you write for your tools, such as `CLAUDE.md`, `AGENTS.md` or rules files.
- **Commit as you go**, with real commit messages. `FIRST_HOUR.md` must be committed before your first code change.
- **Write the documents yourself.** Use AI to check your thinking, but `FIRST_HOUR.md`, `RULINGS.md`, `REFLECTION.md` and the stakeholder replies in `DECISIONS.md` must be in your own words. AI drafting is fine for the rest.
- **Use any LLM provider.** Anthropic, OpenAI, Gemini, Groq, OpenRouter and local models through Ollama all work (see `.env.example`). Tell us which you used. If API costs are a problem, ask us for a capped key.
- **Unit tests must pass without network access or API keys.** Use the fake client.
- **Keep the stack**: a Python backend and a React with TypeScript frontend. Within it, add any libraries you like and tell us why.
- **Keep the batch command in [`docs/OUTPUT_CONTRACT.md`](docs/OUTPUT_CONTRACT.md) working.** It must also work on documents and reference data other than the ones in this repository.
- **Questions:** email careers@moring.ai with "Ledgerline" in the subject. We reply within one working day. If something is ambiguous, a written, reasonable assumption is a perfectly good answer, and often a better one than a question.

## What your final commit should contain

1. Your code changes, with an updated **Running my version** section at the end of this file if setup changed.
2. In `submission/`: `FIRST_HOUR.md`, `FINDINGS.md`, `RULINGS.md`, `EVAL_REPORT.md`, `DECISIONS.md`, `REFLECTION.md` and `AI_USAGE.md`.
3. `submission/ai-logs/`, containing your AI session transcripts.
4. `submission/predictions_dev.jsonl` and `submission/predictions_disputed.jsonl` from your final pipeline (`make predict`).

## Setup

You need Python 3.11+, Node 20+ and `make`. On Windows, use WSL. If your `python3` is older than 3.11, run `make setup PYTHON=python3.12` (or whichever newer version you have). Clone your own repository (see "How to submit"), then, in it:

```bash
cp .env.example .env      # choose a provider and model
make setup                # Python virtualenv and npm install
make test                 # starter tests (offline)
make dev                  # API on :8000, UI on http://localhost:5173
make predict              # writes submission/predictions_dev.jsonl and predictions_disputed.jsonl
make eval                 # the starter's eval script
```

`LLM_PROVIDER=fake` lets you click around the UI without a key. It returns the same canned extraction for every document.

**Watch your spend.** The starter is expensive to run. Set a spending limit with your provider before you run it over all the documents.

## What's in the repository

```
docs/
  AP_POLICY.md            the written business rules (version 3.2)
  OUTPUT_CONTRACT.md      the batch command and predictions format
  PRODUCT_BRIEF.md        users, volumes and workflow
  ARCHITECTURE.md         the original design doc (March 2026)
  HANDOVER.md             the contractor's handover note (October 2026)
  STAKEHOLDER_THREAD.md   emails you need to respond to
data/
  invoices/dev/           24 labeled documents (.txt OCR text, .eml email, .json e-invoice)
  invoices/disputed/      6 unlabeled documents the AP team argues about
  ground_truth/dev.jsonl  labels for the dev set, following the written policy literally
  reference/              buyer.json, vendors.csv, paid_invoices.csv
backend/                  FastAPI app, pipeline, CLI, eval script and tests
frontend/                 React review UI (Vite)
submission/               templates for your write-ups
```

## FAQ

**Can I rewrite it from scratch?** You can, but working in an existing codebase is the job. If you rewrite, show that you kept everything the business relies on, and explain why a rewrite beat fixing.

**Can I use a local model?** Yes. Report its quality honestly, next to whatever you would recommend for production.

**What if I run out of time?** Stop, and tell us what you would do next and why.

**How long should I spend?** About 6 hours, and please stop at 8. Tell us roughly how long you took in `AI_USAGE.md`.

**Is the data real?** No. Every company, GSTIN and bank account in this repository is fictional.

## Running my version

The setup and the batch command are unchanged: `cp .env.example .env`, `make setup`, `make test`, `make dev`, and the
command in `docs/OUTPUT_CONTRACT.md`. What changed is below.

### Setup on Windows without WSL

I developed and verified this natively on Windows (Python 3.12, Node 20+). The Makefile's targets use Linux paths
(`.venv/bin`), so on Windows run their equivalents:

```powershell
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -e ".\backend[dev]"
cd frontend; npm ci; cd ..
cd backend; .venv\Scripts\python -m pytest -q          # make test
```

### Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER`, `LLM_MODEL` | `anthropic`, `claude-opus-5-5` | The primary extraction model. **Recommended:** `claude-haiku-5-5`. |
| `LLM_ESCALATION_MODEL` | unset (no escalation) | Used only when the primary cannot produce a usable extraction (provider error or outage, unusable reply, missing critical field, unreadable value). **Recommended:** `claude-opus-5-5`. |
| `LLM_ESCALATION_PROVIDER` | the primary's | Put the escalation model on another provider to survive an outage of the first. |
| `LEDGERLINE_FLAG_LINE_ARITHMETIC` | off | `1` adds `line_amount_mismatch` (quantity × rate ≠ line amount). Not in AP_POLICY; see RULINGS. |
| `LEDGERLINE_FLAG_FUTURE_DATED` | off | `1` adds `future_dated` (invoice dated after it was sent or processed). Not in AP_POLICY; see RULINGS. |
| `LEDGERLINE_ENV` | unset (= production) | `development` allows approve and reject from this machine only. **Never set it on a server** (see "Known limitation" below). `make dev` sets it for the API. |

The `.env.example` defaults are the starter's (Opus, no escalation). They work, but cost ₹1.77 a document with a
p95 of 11.9 s on the sample, against ₹0.11 and 5.3 s for the recommended Haiku → Opus setup (EVAL_REPORT).

### Tests

- Backend, offline: `make test` (349 tests; no network or API key).
- Frontend: `cd frontend && npm test` (Vitest, added as a dev dependency because the UI had no test runner) and
  `npm run build`. CI runs both.

### Batch predictions and the output contract

The command is unchanged and still works on any folder of documents and reference data. `make predict` writes both
files with the same environment; the submitted files were produced with the flags **off** for dev and **on** for the
disputed set, so run them separately (from `backend/`):

```bash
python -m ledgerline.cli predict --input ../data/invoices/dev --reference ../data/reference \
    --output ../submission/predictions_dev.jsonl
LEDGERLINE_FLAG_LINE_ARITHMETIC=1 LEDGERLINE_FLAG_FUTURE_DATED=1 \
python -m ledgerline.cli predict --input ../data/invoices/disputed --reference ../data/reference \
    --output ../submission/predictions_disputed.jsonl
python eval/check_contract.py ../data/invoices/dev ../submission/predictions_dev.jsonl
python eval/check_contract.py ../data/invoices/disputed ../submission/predictions_disputed.jsonl --flags-on
```

The submitted predictions are the recorded responses of the paid Haiku run read by commit `64a7d51` (no new calls;
the later commits do not change the batch pipeline). EVAL_REPORT explains which numbers come from real calls and
which from replaying recorded responses.

### Evaluation

`backend/eval/baseline_starter.py` runs the pipeline on real model calls with every response cached, every call
logged and a hard cap on calls and spend; `backend/eval/score_predictions.py` scores predictions against the dev
labels. Usage is at the top of each script; the recorded runs are in `submission/baseline/`. Raw responses are
cached in `submission/baseline/llm_cache/`, which is git-ignored.

### Output contract: documents that could not be processed

Ledgerline never skips a document. When it cannot extract one reliably (the provider fails, the model's answer
contains no usable JSON, a value cannot be parsed, or the file is not valid UTF-8), the batch still writes a line
for it with `needs_review: true` and `"processing_error"` in `review_reasons`.

On such a line, every field the extraction did not reliably produce is `null`. Nothing is guessed:

| Field | Contract type | On a `processing_error` line |
|---|---|---|
| `supplier_gstin`, `bank_account`, `ifsc`, `po_number` | string or null | `null`, within the contract |
| `supplier_name`, `invoice_number`, `currency` | string | `null`: **deliberate deviation** |
| `invoice_date` | `"YYYY-MM-DD"` | `null`: **deliberate deviation** |
| `subtotal`, `cgst`, `sgst`, `igst`, `round_off`, `total` | string | `null`: **deliberate deviation** (the starter already did this for unreadable amounts) |
| `document_type` | `"invoice"` or `"credit_note"` | `"invoice"`, the conservative choice because an invoice needs approval |
| `line_items` | list | `[]` |
| `required_approvals` | integer | `1`, provisional (see below) |

Why `null` instead of `""`, `"0.00"` or a date: any of those would look like a real value read from the document.
Consumers of the batch output should treat `"processing_error"` as "fields unknown" and send the document to review.

`required_approvals: 1` on these lines does **not** make the document payable. The API refuses to approve a
document with an unresolved `processing_error` (HTTP 409), so no approval and no payment instruction can be
recorded for it.

### Approvals and payment instructions

AP_POLICY section 4 is enforced on the server, inside one SQLite transaction per decision (`BEGIN IMMEDIATE`),
and backed by database constraints, so it holds under double-clicks, retries and simultaneous requests:

- **Exactly one payment instruction per invoice**: unique index `payments_one_per_invoice`.
- **One person approving twice counts once**: unique index `approvals_one_per_person`. A retry by someone who has
  already approved returns 200 and changes nothing; a different person approving an approved invoice gets 409.
- **Never approvable (409)**: credit notes, duplicates, rejected invoices, unresolved `processing_error`.
- **Approved invoices cannot be rejected (409)**: their payment instruction already exists.
- **Approving a document that needed review requires a note (422).** Rejection notes are optional.
- **Audit log**: every approval and rejection is recorded in `audit_log` (who, when, which invoice, note). If any
  step fails, the approval, status change, payment instruction and audit entry are all rolled back together.
- **Organisations**: invoice detail, approve and reject only see the caller's organisation; another
  organisation's invoice is reported as not found (404).

Existing databases are migrated on start-up: the `audit_log` table and the unique indexes are added. If an existing
database already contains duplicate payment instructions (or the same approver twice on one invoice), Ledgerline
refuses to start and names the affected invoices. Those are real double payments that finance must resolve first;
no rows are changed.

### Known limitation: approver identity is not authenticated

`user_id` (request body) and the organisation (`X-Org-Id` header) are whatever the caller sends. The rules above
stop the same *name* from approving twice; they **do not prove that two different real people approved**, and they
do not stop someone from typing another person's name or another organisation's ID. Before Ledgerline handles
every invoice, both values must come from authentication (for example Meridian's SSO), not from the request.
There is also no role check: nothing limits approval to the AP Lead and the Finance Controller.

**Production blocker, enforced in code.** Until verified authentication and role-based authorization exist, the
approve and reject endpoints refuse every request (HTTP 403) unless **both** of these hold:

- `LEDGERLINE_ENV=development`, and
- the request comes from this machine (127.0.0.1 or ::1; the Vite dev server proxies the UI's calls from there).

Unset `LEDGERLINE_ENV` counts as production. **No setting enables approvals in production**; lifting the block means
implementing authentication (`backend/ledgerline/safeguard.py`). Reading, uploading and the batch command are not
affected. `make dev` sets `LEDGERLINE_ENV=development` for the API, and the test suite runs as development. On
Windows without `make`, start the API with `$env:LEDGERLINE_ENV="development"` (PowerShell) before `uvicorn`.
Never set `development` on a shared or production server: behind a reverse proxy on the same host every caller
looks local.
