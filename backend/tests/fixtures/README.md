# Test fixtures

`opus55_dev_001_call1_extract.txt` and `opus55_dev_001_call2_verify.txt` are real Claude Opus 5.5 responses
for `data/invoices/dev/dev_001.txt`, recorded during the baseline run of the unchanged starter
(`backend/eval/baseline_starter.py`, 18 Nov 2026).

They are **sanitised copies**: the only edit is that bank account numbers are masked to their last four digits
(`XXXXXXXXXX5678`), so the repository does not publish full account numbers (AP_POLICY section 5.1).
Everything else, including the Markdown fence and the prose around the JSON, is byte-for-byte as the model
returned it. The unmasked originals are kept locally and are not committed.
