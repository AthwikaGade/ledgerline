"""Turn the strings the model copies off the page into Python values."""
from __future__ import annotations

import re
from datetime import date

from dateutil import parser as dateparser

# AP_POLICY 1: Indian digit grouping, a Rs./₹/INR prefix and a "/-" suffix. Nothing else is accepted: no text after
# the amount, no other currency symbols, and none of float()'s extras (nan, inf, 1e5).
_AMOUNT = re.compile(r"(?:₹|INR|Rs\.?)?\s*(-?\d[\d,]*(?:\.\d+)?)\s*(?:/-)?")


def parse_amount(value) -> float | None:
    """'₹ 1,23,456.00' -> 123456.0, 'Rs. 1,00,819/-' -> 100819.0. Raises ValueError for anything else."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _AMOUNT.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"not an amount: {value!r}")
    return float(match.group(1).replace(",", ""))


_LEADING_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_leading_number(value) -> float | None:
    """Lenient, for QUANTITIES ONLY: '12 BOX' -> 12.0, '2,000 kg' -> 2000.0, 'as agreed' -> None.

    Quantity is used by no AP policy rule except the flagged line-arithmetic check, which skips lines without one.
    Money is never parsed this way: amounts and prices go through parse_amount, which refuses what it cannot read."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _LEADING_NUMBER.search(str(value))
    return float(match.group(0).replace(",", "")) if match else None


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_date(value, month_first: bool = False) -> date | None:
    """AP_POLICY 1: Indian vendors print the day first (DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY); vendors whose
    country in the vendor master is US print the month first. ISO dates (YYYY-MM-DD) are read as ISO."""
    if not value:
        return None
    text = str(value).strip()
    if _ISO_DATE.fullmatch(text):
        return date.fromisoformat(text)
    return dateparser.parse(text, dayfirst=not month_first).date()
