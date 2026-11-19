# How I worked with AI

## Tools and models

- **Coding assistant:** Claude Code (VS Code extension), model Claude Opus 5.5. One continuous session, exported to
  `ai-logs/`.
- **Other AI tools:** none. Claude Code was the only AI tool I used.
- **Models inside Ledgerline (the evaluated pipeline):** Anthropic API. Claude Opus 5.5 for the starter baseline and
  the same-model comparison; Claude Haiku 5.5 as the primary extraction model with Opus 5.5 as the escalation model
  for the final pipeline. API spend: $5.30 recorded by the evaluation recorder (capped at $8), plus about $0.16 for
  two early smoke-test calls made before the recorder existed.

## How I set up context

- No `CLAUDE.md` or rules file. I pasted the assignment README into the chat and asked for a step-by-step plan with
  the reason for each step.
- I asked the assistant to read `docs/` and the backend **read-only** before any change, and cross-checked its notes
  against my own reading before writing FIRST_HOUR.md myself.
- Working rules I set early and repeated throughout: no commit or push without my explicit approval; every decision
  proposed to me first with its reason; no AI co-author lines in commits; failing tests and saved "before" evidence
  before any fix; no paid API call without my approval and a stated cap; check every step against the README's rules.
- No planning mode. The assistant kept short memory notes outside the repository (my working rules and open
  questions such as disp_04 and disp_06).

## My workflow

- **I decided, the AI proposed.** For each fix: root cause and policy clause, failing tests run against the
  committed code and saved to `submission/evidence/`, the smallest proposed change, then my approval, then the
  change, the full suite and a staging scan (keys, personal paths, account numbers) before each commit.
- **Money was spent only on approved, capped runs.** The assistant wrote a recorder (`backend/eval/baseline_starter.py`)
  that caches every response, logs every call and enforces a spending cap, so code changes could be re-scored for
  free instead of re-paying.
- **How I checked its output:** I asked for real reproductions rather than descriptions (for example the double
  payment reproduced against SQLite before any approval code changed); I asked for tests that fail for the right
  reason and saw the failure messages; I asked for all 30 predictions to be validated against OUTPUT_CONTRACT (the
  assistant added negative controls to show the checker fails when it should); I asked it to separate real calls
  from cached replays in the evaluation.
- **What I wrote myself:** FIRST_HOUR.md, RULINGS.md, the stakeholder replies in DECISIONS.md, REFLECTION.md,
  FINDINGS.md and EVAL_REPORT.md. For FINDINGS and EVAL_REPORT, the assistant first drafted versions from our actual
  results that I replaced with my own; for FINDINGS it then filled in the exact functions, commits and test names from
  the repository and checked my eight findings against the evidence. The other DECISIONS sections, the README's
  "Running my version" and this file were drafted by the assistant and reviewed and edited by me.

## Where the AI was wrong

Times are UTC; each transcript message shows its time.

1. **It recommended WSL, and I followed it** (22:13 to 00:30 UTC on the clock). The README says "On Windows, use WSL", so the
   assistant walked me through installing Ubuntu under WSL. The install failed ("Catastrophic failure"), then `apt`
   downloads kept failing with hash and signature errors on my network. Only then did it check what Windows already
   had (Python 3.12, Node, git; only `make` missing) and switch to a native Windows setup, running the Makefile's
   commands in their Windows form. It should have checked the existing tools first.
   *Transcript: `ai-logs/00_first_hour_claude_code.md`, from 2026-11-17 22:13 (the WSL recommendation) to
   2026-11-18 00:30 (the switch to Windows).*

2. **Its "slim prompt" design dropped something the starter's examples had been doing, and I approved it.** For the
   privacy fix it recommended a one-call prompt without the starter's three example documents (option B), and I
   chose it. The paid Opus run then returned quantities with units ("12 BOX", "750 kg"), which the parser rejected:
   7 of 30 documents became `processing_error`, 3 of them clean invoices, and dev_015's duplicate was hidden behind
   the error. Nothing was skipped or paid, but the run had to be re-scored after a fix (quantity read leniently;
   money kept strict). The examples had implicitly taught the output format, and unit tests with canned responses
   could not catch that; only the evaluation on real responses did.
   *Transcript: `ai-logs/01_main_session_claude_code.md`, 2026-11-18 19:43 (option B recommended), 19:49 (I chose
   it), 20:24 (root cause found after the paid run).*

3. **Its first masking design would have let an account number through, and I caught it.** It masked long numbers
   except on lines labelled invoice, PO or reference, to keep all-digit invoice numbers readable, and listed that as a
   limitation. I pointed out that an account printed under a misleading label ("Invoice Ref: 5020…") would then reach
   the model, against AP_POLICY 5.1. It replaced the design with masking every 9+ digit run whatever its label and
   restoring numbers locally from tokens, and added tests with unknown accounts under misleading labels for both the
   primary and the escalation model. *Transcript: `ai-logs/01_main_session_claude_code.md`, 2026-11-18 20:00 (the
   limitation stated), 20:04 (my correction).*

4. **It presented misleading "before" evidence, then flagged it itself.** Running the new privacy tests against the
   old commit in a temporary worktree, 55 unit tests of a module that did not exist at that commit appeared to pass:
   the editable install's import hook had loaded the new module from the working tree. It caught this before I relied
   on it, re-ran with those tests deselected, and wrote the reason into the evidence file.
   *Transcript: `ai-logs/01_main_session_claude_code.md`, 2026-11-18 19:56.*

5. **It wrote tests that were wrong, not the code.** A contract test required a specific JSON key order (the
   contract defines fields, not order); an audit-log test compared `sqlite3.Row` objects to tuples; after the switch
   to one LLM call per document, two tests passed for the wrong reason because their fake model queues still assumed
   two calls. Each was found by reading the failure or by asking "is this test still testing what it says?".
   *Transcript: `ai-logs/01_main_session_claude_code.md`, 2026-11-18 18:50 (key order), 19:30 (Row vs tuple), 20:00
   (fake queues).*

## What I deliberately didn't delegate, and why

- **The rulings on the six disputed documents**, the stakeholder replies and the reflection: they are judgement calls
  I have to defend in my own words.
- **Every commit and every paid run.** I approved each one after seeing the staged files, the scan and the cost cap.
- **Departures from the written policy.** The assistant proposed flags; I decided which documents to rule on and
  that every departure stays behind a flag that is off by default.
- **What counts as evidence.** I asked for estimates to be labelled as illustrative, for the ₹1,06,495 to be called
  potential duplicate-payment exposure rather than loss, and for cached replays to be distinguished from real calls.

## Time

**How it is counted, without double-counting.** In-session time is measured from the session log: the time between
consecutive messages, wherever the gap is 20 minutes or less. Any gap longer than 20 minutes is excluded, and only
those excluded gaps can hold offline work (reading the docs, writing my own documents), which I add from my own
estimate. Time inside an in-session stretch (for example reading the assistant's replies or waiting for a paid run)
is counted once, in that stretch. This undercounts a little: a paid run I waited on for more than 20 minutes without
a message is not counted.

| Stretch | Where | Hours |
|---|---|---|
| Setup: template repository, failed WSL install, native Windows setup | in session (measured) | 1.7 |
| Reading the docs and writing FIRST_HOUR.md | offline (my estimate) | 0.3 |
| API key, smoke test, first transcript, FIRST_HOUR commit | in session (measured) | 0.8 |
| Baseline runs, never-drop-a-document fix, routing and duplicates | in session (measured) | 1.5 |
| Approvals and payment safety | in session (measured) | 0.2 |
| Privacy, cost reporting, escalation | in session (measured) | 0.6 |
| Paid evaluations, disputed-document flags, final fixes, report drafts | in session (measured) | 1.7 |
| RULINGS, stakeholder replies, REFLECTION and my other documents | offline (my estimate) | 0.4 |
| Final review, clean-clone check, submission | in session (measured) | 1.4 |
| **Total, excluding setup** (6.2 h in session + 0.75 h offline; rows are rounded) | | **about 7.0** |

## Transcripts

- `ai-logs/00_first_hour_claude_code.md`: setup, reading, planning, FIRST_HOUR.md (exported before any code change).
- `ai-logs/01_main_session_claude_code.md`: everything after that, to the end of the session.

Both are exported from the Claude Code session log, with thinking blocks omitted, long tool output truncated, my
email address and anything resembling an API key redacted, and my Windows username, local paths, GitHub username and
name replaced with placeholders (`<home>`, `<user>`, `<claude-project-dir>`, `<github-user>`, `<name>`); in the main
session, the two bank account numbers quoted from sample invoices are masked to their last four digits. Nothing else
in the conversation was changed. The first-hour transcript was committed before this redaction existed; its
redaction is a separate later commit, and the original remains in the repository's history.
