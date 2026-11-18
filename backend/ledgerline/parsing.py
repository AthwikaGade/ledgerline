"""Turn the strings the model copies off the page into Python values."""
from __future__ import annotations

import re
from datetime import date

from dateutil import parser as dateparser


def parse_amount(value) -> float | None:
    """'₹ 1,23,456.00' -> 123456.0"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("₹", "").replace("INR", "").replace(",", "").strip()
    return float(cleaned)


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
