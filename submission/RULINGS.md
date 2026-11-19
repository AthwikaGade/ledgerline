# Rulings on the disputed documents

## My flags

I added two extra checks because I felt the original policy was missing a few things. Both are turned off by default, so they don't change the existing policy unless we choose to use them.

- **`LEDGERLINE_FLAG_LINE_ARITHMETIC=1`:** Checks if the quantity multiplied by the price matches the amount shown on the invoice. It allows a ₹1 difference. This is for **disp_05** and adds `line_amount_mismatch`.
- **`LEDGERLINE_FLAG_FUTURE_DATED=1`:** Checks if the invoice date is later than the email date or processing date. This is for **disp_06** and adds `future_dated`.

I turned on both flags when generating `predictions_disputed.jsonl`.

## disp_01

- **Ruling:** Needs review for `gstin_invalid` and `vendor_unknown`. It requires 1 approval.
- **It rests on:** The AP policy uses GSTIN to identify Indian suppliers. Sitara's GSTIN has a `B` instead of an `8`, so it doesn't pass validation and the system can't confirm the supplier.
- **The best argument against my ruling:** The name and bank details match Sitara. It could just be a typing or printing mistake.
- **The policy change I'd propose, if any:** Show possible supplier matches to the reviewer, but don't automatically change the GSTIN.
- **Implemented?** Yes. The existing GSTIN and supplier checks handle this. No extra flag was needed.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes. It shows both review reasons and 1 approval.

## disp_02

- **Ruling:** Needs review for `duplicate`. It shows 1 required approval, but the invoice cannot be approved for payment.
- **It rests on:** The AP policy doesn't allow duplicate payments. The original invoice for ₹34,220 was already paid, and the revised invoice uses the same number but asks for ₹35,872.
- **The best argument against my ruling:** The supplier might genuinely be owed the extra ₹1,652 because of a price change.
- **The policy change I'd propose, if any:** Allow suppliers to submit a separate adjustment for the difference instead of reusing an already-paid invoice.
- **Implemented?** Yes. Duplicate detection and payment blocking are already implemented. No extra flag was needed.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes. It flags the duplicate and blocks payment approval.

## disp_03

- **Ruling:** Needs review for `foreign_currency` and requires 2 different approvals.
- **It rests on:** The AP policy treats invoices in currencies other than INR as foreign. Narmada is an Indian supplier, but the invoice amount is in USD.
- **The best argument against my ruling:** The supplier is in India, has an Indian bank account, and accepts payment through NEFT/RTGS.
- **The policy change I'd propose, if any:** Make the rules clearer for Indian suppliers who send invoices in foreign currencies.
- **Implemented?** Yes. The existing currency checks and approval rules handle this. No extra flag was needed.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes. It shows `foreign_currency` and 2 approvals.

## disp_04

- **Ruling:** Needs review for `suspicious_content` and requires 1 approval.
- **It rests on:** The AP policy says text directed at automated systems should be flagged. Here, Vardhan asks the AP system to include the invoice number in the payment details.
- **The best argument against my ruling:** The message looks harmless. The supplier isn't asking the system to skip any checks.
- **The policy change I'd propose, if any:** Make it clearer which messages are actually suspicious so normal supplier instructions don't get flagged unnecessarily.
- **Implemented?** Yes. The existing suspicious-content check handles this. No extra flag was needed.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes. It flags `suspicious_content` and requires 1 approval.

## disp_05

- **Ruling:** Needs review for `line_amount_mismatch` and requires 1 approval when my extra check is on.
- **It rests on:** The invoice says 4 gauges cost ₹3,850 each, which should be ₹15,400. But the printed amount is ₹15,950. The original policy checks the overall total, so it misses this ₹550 difference.
- **The best argument against my ruling:** Some invoices may have discounts or special pricing, so not every difference is necessarily a mistake.
- **The policy change I'd propose, if any:** Add a check that compares quantity, unit price, and line amount, allowing a ₹1 difference.
- **Implemented?** Yes, through `LEDGERLINE_FLAG_LINE_ARITHMETIC`, with tests for both on and off.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes. With the flag on, it reports `line_amount_mismatch` and sends the invoice for review.

## disp_06

- **Ruling:** Needs review for `future_dated` and requires 1 approval when my extra check is on.
- **It rests on:** The email was sent on 28 April 2026, but the invoice is dated 25 June 2026. The original policy doesn't check for this kind of date difference. It could also affect whether the supplier is treated as new.
- **The best argument against my ruling:** The email date might not be reliable, or the supplier may have entered the wrong date by mistake.
- **The policy change I'd propose, if any:** Add a check for unusual date differences, but don't automatically change the invoice date.
- **Implemented?** Yes, through `LEDGERLINE_FLAG_FUTURE_DATED`, with tests for both on and off.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes. With the flag on, it reports `future_dated` and sends the invoice for review.

## The two I consider riskiest, and why

**disp_05:** The final total looks correct at first, but one item is charged ₹550 more than it should be, or ₹649 including GST. If we only check the final total, we could end up paying extra.

**disp_06:** The invoice date is almost two months later than the email date. It might be a simple mistake, but it could also affect whether the supplier goes through the new-vendor checks.

I chose these two because the original policy would have marked them as ready. Without the extra checks, these issues could easily be missed.
