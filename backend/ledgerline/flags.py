"""Feature flags for departures from the written AP policy (docs/AP_POLICY.md is never changed by code).

A flag is on only when its environment variable is exactly "1". All are off by default, so without them Ledgerline
applies AP_POLICY v3.2 literally. Each flag may add one review-reason code that is not in the policy.

    LEDGERLINE_FLAG_LINE_ARITHMETIC=1  -> line_amount_mismatch  (disp_05: quantity x rate != line amount)
    LEDGERLINE_FLAG_FUTURE_DATED=1     -> future_dated          (disp_06: invoice dated after it was sent/processed)
"""
from __future__ import annotations

import os

FLAGS = {
    "LINE_ARITHMETIC": "line_amount_mismatch",
    "FUTURE_DATED": "future_dated",
}


def flag_enabled(name: str) -> bool:
    return os.getenv(f"LEDGERLINE_FLAG_{name}") == "1"
