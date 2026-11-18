# My first hour

*Under about 300 words, in your own words. Commit it on its own, before any commit that touches `backend/` or `frontend/`, and don't edit it afterwards. Save the AI sessions from this stretch in `ai-logs/` with a name starting `00_first_hour`. Being wrong here is fine.*

## What I think is going on

I've gone through the documentation and looked at the code briefly for basic understanding. I feel the biggest problem with the app "Ledgerline" is that we are depending on the LLM to make final decisions. But as per the documentation, the original approach says we should use AI for extraction purposes and code for validation. With these issues, I don't think the app is ready for a full rollout yet.

## The risks I suspect, most serious first

1. **Duplicate payments:** Since the Approve button is slow, clicking it multiple times could create multiple payments for the same invoice.
2. The LLM is making the final decision even though validation checks are performed. This could allow incorrect invoices to be paid.
3. The vendor master is included in the prompt. I'll go through it and check if it is sharing any sensitive banking information of vendors.
4. They reported 94.2% accuracy, but I don't know how safe the system is now.
5. Reviewers can't easily verify extracted values. Here, I feel the purpose of automation is missing.
6. Approval rules aren't being followed properly.

## My plan for the time I have

I want to focus on the issues that are directly causing financial loss first. Then I'll reproduce the problems, build a baseline, fix the important defects with tests, go through the disputed invoices, and improve the reviewer experience. I'll use the remaining time for evaluation and documentation rather than rewriting the entire application.

## What I would ask Meridian

1. How are approver identities verified?
2. How many unnecessary reviews can the AP team handle in reality?
3. How are bank account changes currently verified?
4. Who approves future policy changes?
