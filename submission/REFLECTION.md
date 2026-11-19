# Reflection

## Three things I didn't know when I started, and how I learned each one

1. **High AI accuracy doesn't always mean the system is safe.**

   At first, I thought a model with around 94% accuracy would be reliable enough. But when I ran the evaluation, I found that two duplicate invoices were marked as ready for payment. I learned that extracting information correctly and making the right payment decision are two different things. That's why I moved the policy checks into Python instead of depending on the AI.

2. **A working Approve button doesn't mean payments are protected.**

   I didn't realize how easily repeated requests could create multiple payments. During testing, a double-click created two payment instructions, and eight simultaneous requests created eight. I learned why database constraints and transactions are important, instead of depending only on frontend checks.

3. **Sending data to an AI model needs more care than I expected.**

   I found that the original system was sending full bank account numbers to the model. This made me understand why sensitive information should be handled locally and masked before being sent outside. I also learned that fixing one security issue doesn't mean the whole application is secure.

## The decision I'm least sure of

I'm least sure about adding the future-date check for invoices.

I added it because an invoice dated later than its email could be suspicious, especially when the date affects the new-vendor rule. But I also understand that email dates aren't always reliable, and it could just be a genuine mistake.

That's why I kept this check optional and turned off by default. I would test it on more real invoices and ask the Finance team for feedback. If it creates too many unnecessary reviews without finding real problems, I would reconsider the rule.

## With one more week

First, I would work on authentication and role-based authorization because payment approvals should only be handled by verified employees. Right now, the production approval endpoints are blocked as a safety measure, but that isn't a complete solution.

Next, I would test the system with more real invoices, including different formats and suppliers. The current results look good, but the dataset is small, so I want to see how it performs in real situations.

After that, I would build the evidence view so reviewers can see exactly where each extracted value came from. I would also work with the AP team on the bank-change verification process.

Finally, I would improve the reviewer experience, especially the Approve button's loading feedback, and check the system's performance under heavier usage.

My main goal would be to make the system not just accurate, but also safe and practical for the people using it every day.

## What I cut, and why

I couldn't finish everything within the time limit, so I focused on the things that mattered most for payment safety. I chose option B instead of building the evidence-linked review screen because I wanted to fix payment risks and improve reliability first. I also left authentication and user roles for later because they needed more time, so I blocked production approvals instead. I didn't build the bank-change call-back process because I wanted AP's input first. I skipped another expensive evaluation run and postponed smaller frontend improvements, including the Approve button's loading feedback.
