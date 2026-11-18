"""Deterministic AP policy checks (docs/AP_POLICY.md v3.2, sections 1, 3 and 4).

Code, not the model, decides whether a document needs review, every reason why, and how many approvals it needs.
The model only extracts fields; whatever it says about routing is advisory.

Money is compared as Decimal rounded to paise. Amounts are still stored as REAL in SQLite (see README, known
limitations), so each value is converted with Decimal(str(value)), which recovers the two-place amount exactly.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from decimal import Decimal
from email.utils import parsedate_to_datetime

from .flags import flag_enabled
from .models import Invoice
from .reference import ReferenceData

GSTIN_PATTERN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DEFAULT_BUYER_STATE_CODE = "27"  # Maharashtra; the reference data's buyer.json takes precedence
TOTALS_TOLERANCE = Decimal("1.00")
HIGH_VALUE_THRESHOLD = Decimal("500000.00")
VENDOR_NEW_DAYS = 90
PAISE = Decimal("0.01")

# The order of AP_POLICY section 3, used to report reasons consistently.
REASON_ORDER = ["credit_note", "duplicate", "gstin_invalid", "vendor_unknown", "vendor_new", "bank_details_changed",
                "tax_type_mismatch", "totals_mismatch", "foreign_currency", "suspicious_content", "processing_error",
                # Not in AP_POLICY v3.2: only ever raised when their flag is on (see flags.py).
                "line_amount_mismatch", "future_dated"]

# suspicious_content: "text addressed to automated systems or AI (for example, instructions to skip checks or
# change an approval decision), or embedded HTML or script markup". Deterministic and deliberately specific.
_MARKUP = [
    r"<\s*/?\s*(script|iframe|img|svg|object|embed|form|input|link|meta|style|html|body|a)\b[^>]*>",
    r"\bon[a-z]+\s*=\s*[\"']",
    r"javascript\s*:",
]
_ADDRESSED_TO_MACHINES = [
    r"\b(for|to|attention)\b[^.\n]{0,40}\b(automated|automation|LLM|language models?|assistants?|bots?)\b",
    r"\b(for|to|attention)\b[^.\n]{0,40}\bAI\b",
]
_INSTRUCTIONS = [
    r"\bignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier|other)\s+(instructions|rules|prompts?)",
    r"\b(requires_review|review_reasons|required_approvals|needs_review)\b",
    r"\b(set|mark|route|treat|classify)\b[^.\n]{0,40}\b(as\s+)?(ready|approved|pre-?approved|safe|verified)\b",
    r"\b(skip|bypass|disable|override)\b[^.\n]{0,30}\b(checks?|validation|review|verification|policy)\b",
    r"\bdo\s+not\s+(flag|review|mention|report)\b",
]
_SUSPICIOUS = [re.compile(p, re.IGNORECASE) for p in _MARKUP + _ADDRESSED_TO_MACHINES[:1] + _INSTRUCTIONS] + [
    re.compile(_ADDRESSED_TO_MACHINES[1])  # "AI" only as the upper-case acronym
]


# --- Normalisation (AP_POLICY section 1) -------------------------------------------------------------------------

def money(value) -> Decimal | None:
    """Exact two-place Decimal for an amount, or None when the amount is unknown."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(PAISE)


def normalize_invoice_number(number: str | None) -> str:
    """Uppercase, with spaces and the characters / - # . removed. Leading zeros are significant."""
    return re.sub(r"[\s/\-#.]", "", number or "").upper()


def normalize_name(name: str | None) -> str:
    """Legal name compared case-insensitively, ignoring spaces and punctuation."""
    return re.sub(r"[\W_]", "", (name or "").lower())


def normalize_gstin(gstin: str | None) -> str:
    """Formatting only (surrounding spaces, letter case). Characters are never corrected or guessed."""
    return re.sub(r"\s", "", gstin or "").upper()


def financial_year(day: date) -> int:
    """1 April to 31 March. Returns the starting year: 2026-04-03 -> 2026 (FY 2026-27), 2026-03-31 -> 2025."""
    return day.year if day.month >= 4 else day.year - 1


def is_domestic(currency: str | None) -> bool:
    return (currency or "").strip().upper() == "INR"


def supplier_key(gstin: str | None, name: str | None, currency: str | None) -> str | None:
    """Domestic: the supplier's GSTIN. Foreign: the normalised legal name."""
    key = normalize_gstin(gstin) if is_domestic(currency) else normalize_name(name)
    return key or None


# --- GSTIN (Appendix A) ------------------------------------------------------------------------------------------

def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return GSTIN_ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str | None) -> bool:
    """Format (15 characters, Appendix A layout) and check character."""
    value = normalize_gstin(gstin)
    return GSTIN_PATTERN.fullmatch(value) is not None and gstin_checksum(value[:14]) == value[14]


# --- Vendor master -----------------------------------------------------------------------------------------------

def find_vendor(ref: ReferenceData, gstin: str | None, name: str | None, currency: str | None) -> dict | None:
    """Domestic suppliers are identified by GSTIN alone (the printed name is not proof). Foreign: supplier key."""
    if is_domestic(currency):
        key = normalize_gstin(gstin)
        return next((v for v in ref.vendors if key and normalize_gstin(v.get("gstin")) == key), None)
    key = normalize_name(name)
    return next((v for v in ref.vendors if key and normalize_name(v.get("legal_name")) == key), None)


def vendor_prints_month_first(vendor: dict | None) -> bool:
    """AP_POLICY 1: vendors whose country in the vendor master is US print MM/DD/YYYY; Indian vendors day first."""
    return bool(vendor) and (vendor.get("country") or "").strip().upper() == "US"


# --- Section 3 checks: each returns the codes that apply ----------------------------------------------------------

def check_credit_note(inv: Invoice) -> list[str]:
    return ["credit_note"] if inv.document_type == "credit_note" else []


def check_gstin(inv: Invoice) -> list[str]:
    if is_domestic(inv.currency) and not is_valid_gstin(inv.supplier_gstin):
        return ["gstin_invalid"]
    return []


def check_vendor(vendor: dict | None) -> list[str]:
    return [] if vendor else ["vendor_unknown"]


def check_vendor_new(inv: Invoice, vendor: dict | None) -> list[str]:
    if not vendor or not vendor.get("onboarded_on") or inv.invoice_date is None:
        return []
    onboarded = date.fromisoformat(vendor["onboarded_on"])
    return ["vendor_new"] if (inv.invoice_date - onboarded).days < VENDOR_NEW_DAYS else []


def check_bank_details(inv: Invoice, vendor: dict | None) -> list[str]:
    """Account numbers digits-only, IFSC case-insensitive. Not raised for unknown vendors or absent details."""
    if not vendor:
        return []
    changed = False
    if inv.bank_account:
        changed |= re.sub(r"\D", "", inv.bank_account) != re.sub(r"\D", "", vendor.get("bank_account") or "")
    if inv.ifsc:
        changed |= inv.ifsc.strip().upper() != (vendor.get("ifsc") or "").strip().upper()
    return ["bank_details_changed"] if changed else []


def check_tax_type(inv: Invoice, buyer_state_code: str = DEFAULT_BUYER_STATE_CODE) -> list[str]:
    gstin = normalize_gstin(inv.supplier_gstin)
    if not is_domestic(inv.currency) or len(gstin) < 2:
        return []
    zero = Decimal(0)
    intra_state = gstin[:2] == str(buyer_state_code).zfill(2)
    if intra_state and (money(inv.igst) or zero) > zero:
        return ["tax_type_mismatch"]
    if not intra_state and ((money(inv.cgst) or zero) > zero or (money(inv.sgst) or zero) > zero):
        return ["tax_type_mismatch"]
    return []


def check_totals(inv: Invoice) -> list[str]:
    """|sum of line amounts + CGST + SGST + IGST + round-off - total| > Rs 1.00. Exactly Rs 1.00 is fine."""
    if inv.total is None or any(item.amount is None for item in inv.line_items):
        return ["totals_mismatch"]  # a missing amount cannot be verified; it is never counted as zero
    zero = Decimal(0)
    computed = sum((money(item.amount) or zero for item in inv.line_items), zero)
    computed += sum((money(v) or zero for v in (inv.cgst, inv.sgst, inv.igst, inv.round_off)), zero)
    return ["totals_mismatch"] if abs(computed - money(inv.total)) > TOTALS_TOLERANCE else []


def check_foreign_currency(inv: Invoice) -> list[str]:
    return [] if is_domestic(inv.currency) else ["foreign_currency"]


def check_suspicious_content(raw_text: str) -> list[str]:
    return ["suspicious_content"] if any(p.search(raw_text or "") for p in _SUSPICIOUS) else []


def _duplicate_key(gstin, name, currency, number, day) -> tuple | None:
    key = supplier_key(gstin, name, currency)
    if not key or not number or day is None:
        return None
    return key, normalize_invoice_number(number), financial_year(day)


def check_duplicate(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, org_id: str = "meridian") -> list[str]:
    """An invoice with the same supplier key, normalised number and FY already exists: in paid_invoices.csv, or
    earlier among this organisation's documents (batches are processed in document_id order, so 'earlier in the
    batch' is 'already stored'). Credit notes are not checked, and only invoices count as earlier matches."""
    if inv.document_type != "invoice":
        return []
    key = _duplicate_key(inv.supplier_gstin, inv.supplier_name, inv.currency, inv.invoice_number, inv.invoice_date)
    if key is None:
        return []
    for paid in ref.paid_invoices:
        currency = "INR" if paid.get("supplier_gstin") else "foreign"  # paid history has no currency column
        paid_day = date.fromisoformat(paid["invoice_date"]) if paid.get("invoice_date") else None
        if _duplicate_key(paid.get("supplier_gstin"), paid.get("supplier_name"), currency,
                          paid.get("invoice_number"), paid_day) == key:
            return ["duplicate"]
    rows = conn.execute(
        "SELECT supplier_gstin, supplier_name, currency, invoice_number, invoice_date FROM invoices "
        "WHERE org_id = ? AND document_type = 'invoice' AND invoice_number IS NOT NULL AND invoice_date IS NOT NULL",
        (org_id,),
    ).fetchall()
    for row in rows:
        if _duplicate_key(row["supplier_gstin"], row["supplier_name"], row["currency"], row["invoice_number"],
                          date.fromisoformat(row["invoice_date"])) == key:
            return ["duplicate"]
    return []


# --- Section 4.1 ------------------------------------------------------------------------------------------------

def required_approvals(inv: Invoice) -> int:
    if inv.document_type == "credit_note":
        return 0
    if not is_domestic(inv.currency):
        return 2
    if inv.total is not None and money(inv.total) >= HIGH_VALUE_THRESHOLD:
        return 2
    return 1


# --- Flagged checks: departures from the written policy, off by default (Part 2 rulings) --------------------------

def today() -> date:
    """The processing date. A function so tests can fix it."""
    return date.today()


_HEADER_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:")


def email_date_header(raw_text: str) -> date | None:
    """The Date: header of an email document, from its header block only (the lines before the first blank line,
    which must look like RFC 5322 headers and include From:). It is SENDER-SUPPLIED: a claim about when the email was
    sent, not a verified receipt timestamp. Ledgerline does not record one for batch documents."""
    lines = (raw_text or "").lstrip("﻿").split("\n")
    block = []
    for line in lines:
        if not line.strip():
            break
        if not _HEADER_LINE.match(line) and not line[:1].isspace():
            return None
        block.append(line)
    if not any(line.lower().startswith("from:") for line in block):
        return None
    for line in block:
        if line.lower().startswith("date:"):
            try:
                return parsedate_to_datetime(line[5:].strip()).date()
            except (TypeError, ValueError):
                return None
    return None


def check_line_arithmetic(inv: Invoice) -> tuple[list[str], list[str]]:
    """|quantity x unit price - line amount| > Rs 1.00 on any line where all three are printed."""
    notes = []
    for number, item in enumerate(inv.line_items, start=1):
        if item.quantity is None or item.unit_price is None or item.amount is None:
            continue
        quantity, rate, amount = Decimal(str(item.quantity)), money(item.unit_price), money(item.amount)
        expected = (quantity * rate).quantize(PAISE)
        if abs(expected - amount) > TOTALS_TOLERANCE:
            notes.append(f"line {number}: {quantity.normalize():f} x {rate} = {expected}, printed {amount} "
                         f"(difference {amount - expected})")
    return (["line_amount_mismatch"], notes) if notes else ([], [])


def check_future_dated(inv: Invoice, raw_text: str) -> tuple[list[str], list[str]]:
    """The printed invoice date (still the document date, AP_POLICY 1) is later than the email's Date header, or
    later than the day Ledgerline processes it. The email date is only a consistency signal; it changes no field."""
    if inv.invoice_date is None:
        return [], []
    notes = []
    sent = email_date_header(raw_text)
    if sent is not None and inv.invoice_date > sent:
        notes.append(f"invoice dated {inv.invoice_date} is later than the email's Date header {sent} "
                     f"(sender-supplied, not a verified receipt time)")
    processed = today()
    if inv.invoice_date > processed:
        notes.append(f"invoice dated {inv.invoice_date} is later than the day it was processed ({processed})")
    return (["future_dated"], notes) if notes else ([], [])


def flagged_checks(inv: Invoice, raw_text: str) -> tuple[list[str], list[str]]:
    """Reasons and reviewer notes from the checks whose flags are on."""
    reasons, notes = [], []
    if flag_enabled("LINE_ARITHMETIC"):
        r, n = check_line_arithmetic(inv)
        reasons, notes = reasons + r, notes + n
    if flag_enabled("FUTURE_DATED"):
        r, n = check_future_dated(inv, raw_text)
        reasons, notes = reasons + r, notes + n
    return reasons, notes


def run_checks(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, raw_text: str = "",
               org_id: str = "meridian") -> list[str]:
    """Every section 3 rule that applies (not just the first), in policy order."""
    vendor = find_vendor(ref, inv.supplier_gstin, inv.supplier_name, inv.currency)
    buyer_state = (ref.buyer or {}).get("state_code") or DEFAULT_BUYER_STATE_CODE
    reasons = (
        check_credit_note(inv)
        + check_duplicate(conn, ref, inv, org_id)
        + check_gstin(inv)
        + check_vendor(vendor)
        + check_vendor_new(inv, vendor)
        + check_bank_details(inv, vendor)
        + check_tax_type(inv, buyer_state)
        + check_totals(inv)
        + check_foreign_currency(inv)
        + check_suspicious_content(raw_text)
    )
    return sorted(set(reasons), key=REASON_ORDER.index)
