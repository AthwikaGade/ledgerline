"""Process one document end to end: extract -> normalise -> check -> route -> persist."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field

from . import db, extraction
from .bank import digits, find_bank_details, still_masked
from .extraction import ExtractionError, extract
from .llm.pricing import cost_usd
from .models import Invoice, LineItem
from .parsing import parse_amount, parse_date, parse_leading_number
from .reference import ReferenceData
from .validation import REASON_ORDER, find_vendor, flagged_checks, run_checks, vendor_prints_month_first
from .validation import required_approvals as policy_approvals

# Without these the policy cannot be applied (the duplicate rule needs number and date, approvals and the totals
# rule need the total and currency), so a document missing any of them is a processing_error, never ready.
CRITICAL_FIELDS = ("document_type", "invoice_number", "invoice_date", "currency", "total")
DOCUMENT_TYPES = ("invoice", "credit_note")


def require_critical_fields(data: dict) -> None:
    missing = [f for f in CRITICAL_FIELDS if data.get(f) is None or str(data.get(f)).strip() == ""]
    if missing:
        raise ValueError(f"extraction is missing critical fields: {', '.join(missing)}")
    if data["document_type"] not in DOCUMENT_TYPES:
        raise ValueError(f"unknown document_type {data['document_type']!r}")
    masked = [f for f in CRITICAL_FIELDS if still_masked(data.get(f))]
    if masked:  # a masked number the model did not copy back exactly cannot be trusted as a value
        raise ValueError(f"masked numbers could not be restored in: {', '.join(masked)}")


def normalize(data: dict, month_first: bool = False) -> Invoice:
    items = [
        LineItem(
            description=str(item.get("description", "")),
            quantity=parse_leading_number(item.get("quantity")),  # '12 BOX' -> 12 (quantity only)
            unit_price=parse_amount(item.get("unit_price")),      # money: strict
            amount=parse_amount(item.get("amount")),              # money: strict, and None stays None (not 0)
        )
        for item in data.get("line_items") or []
    ]
    return Invoice(
        document_type=data.get("document_type") or "invoice",
        supplier_name=data.get("supplier_name"),
        supplier_gstin=data.get("supplier_gstin"),
        invoice_number=data.get("invoice_number"),
        invoice_date=parse_date(data.get("invoice_date"), month_first=month_first),
        currency=(data.get("currency") or "INR").strip().upper(),
        subtotal=parse_amount(data.get("subtotal")),
        cgst=parse_amount(data.get("cgst")) or 0.0,
        sgst=parse_amount(data.get("sgst")) or 0.0,
        igst=parse_amount(data.get("igst")) or 0.0,
        round_off=parse_amount(data.get("round_off")) or 0.0,
        total=parse_amount(data.get("total")),
        bank_account=data.get("bank_account"),
        ifsc=data.get("ifsc"),
        po_number=data.get("po_number"),
        notes=data.get("notes"),
        line_items=items,
    )


def _unknown_invoice() -> Invoice:
    """A document whose fields could not be extracted. `invoice` is the conservative type: it needs approval."""
    return Invoice(document_type="invoice", supplier_name=None, supplier_gstin=None, invoice_number=None,
                   invoice_date=None, currency=None, subtotal=None, cgst=None, sgst=None, igst=None,
                   round_off=None, total=None, bank_account=None, ifsc=None, po_number=None, notes=None)


def apply_local_bank_details(inv: Invoice, raw_text: str, model_account: str | None) -> list[str]:
    """Bank details come from the original document, read locally (the model only saw masked numbers).
    Returns the reasons they could not be verified; an unverified account is treated as changed (review)."""
    local = find_bank_details(raw_text)
    unverified = []
    inv.bank_account = local.accounts[0] if local.accounts else None
    if len(local.accounts) > 1:
        unverified.append(f"{len(local.accounts)} different account numbers appear on the document")
    if not local.accounts and digits(model_account):
        unverified.append("the model reported a bank account that could not be read from the document")
    if local.ifscs:
        inv.ifsc = local.ifscs[0]
        if len(local.ifscs) > 1:
            unverified.append(f"{len(local.ifscs)} different IFSC codes appear on the document")
    elif inv.ifsc:
        inv.ifsc = inv.ifsc.strip().upper()
    return unverified


@dataclass
class Attempt:
    """One model's extraction of a document, checked deterministically."""

    responses: list = field(default_factory=list)
    inv: Invoice | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _attempt(conn: sqlite3.Connection, ref: ReferenceData, raw_text: str, org_id: str, client) -> Attempt:
    try:
        data, responses = extract(raw_text, ref, client=client)
    except ExtractionError as exc:
        return Attempt(responses=exc.responses, error=str(exc))
    try:
        require_critical_fields(data)
        # Identify the vendor before reading the date: US vendors print month first, Indian vendors day first.
        vendor = find_vendor(ref, data.get("supplier_gstin"), data.get("supplier_name"), data.get("currency"))
        inv = normalize(data, month_first=vendor_prints_month_first(vendor))
        unverified = apply_local_bank_details(inv, raw_text, data.get("bank_account"))
        reasons = run_checks(conn, ref, inv, raw_text=raw_text, org_id=org_id)
        flagged, flag_notes = flagged_checks(inv, raw_text)  # off by default; see flags.py
        extra = {*flagged, *(["bank_details_changed"] if unverified and vendor else [])}
        reasons = sorted({*reasons, *extra}, key=REASON_ORDER.index)
        # The model's own routing opinion, if it gave one, is kept for the reviewer but never decides anything.
        warnings = [f"bank details not verified: {u}" for u in unverified] + flag_notes
        if "requires_review" in data or "review_reasons" in data:
            warnings.append(f"advisory only, not used for routing: the model suggested requires_review="
                            f"{data.get('requires_review')!r}, review_reasons={data.get('review_reasons')!r}")
        return Attempt(responses=responses, inv=inv, reasons=reasons, warnings=warnings)
    except Exception as exc:  # noqa: BLE001 - any failure here must become processing_error, never a dropped doc
        return Attempt(responses=responses, error=f"{type(exc).__name__}: {exc}")


def _escalation_trigger(attempt: Attempt) -> str | None:
    """Escalate only when the primary could not produce a usable extraction (provider failure, unusable reply,
    missing critical field, unreadable value). A deterministic review reason is never escalated: a second reading may
    not clear it, so escalating would add cost and latency without changing the decision."""
    if attempt.error is not None:
        return f"primary extraction failed ({attempt.error})"
    return None


def process_document(
    conn: sqlite3.Connection,
    ref: ReferenceData,
    raw_text: str,
    document_id: str,
    org_id: str = "meridian",
    filename: str | None = None,
) -> dict:
    attempts = [_attempt(conn, ref, raw_text, org_id, client=None)]  # primary model (LLM_MODEL)
    trigger = _escalation_trigger(attempts[0])
    escalation_client = extraction.get_escalation_client() if trigger else None
    if escalation_client is not None:
        attempts.append(_attempt(conn, ref, raw_text, org_id, client=escalation_client))
    responses = [r for a in attempts for r in a.responses]
    good = [a for a in attempts if a.error is None]

    if not good:
        # AP_POLICY 3: processing_error always goes to review and is never dropped. Nothing is invented: every
        # extracted field stays unknown (NULL). required_approvals is a provisional 1; it does not make the
        # document payable, because the approve endpoint refuses documents with an unresolved processing_error.
        inv, warnings = _unknown_invoice(), [f"processing_error: {a.error}" for a in attempts]
        needs_review, review_reasons, required_approvals = True, ["processing_error"], 1
        status = "needs_review"
    else:
        # Field values come from the last successful read (the escalated one, if any). Review reasons are the union
        # over every successful read: escalation can add a second opinion but never clear a deterministic reason.
        final = good[-1]
        inv, warnings = final.inv, list(final.warnings)
        review_reasons = sorted({r for a in good for r in a.reasons}, key=REASON_ORDER.index)
        if len(attempts) > 1:
            escalated = attempts[-1]
            model = escalated.responses[-1].model if escalated.responses else "the escalation model"
            outcome = "succeeded" if escalated.error is None else f"failed ({escalated.error})"
            warnings.append(f"escalated to {model} because the {trigger}; escalation {outcome}")
        # Routing is decided by code from AP_POLICY sections 3 and 4 (ARCHITECTURE.md decision 1).
        needs_review = bool(review_reasons)
        required_approvals = policy_approvals(inv)
        status = "needs_review" if needs_review else "ready_for_approval"

    cur = conn.execute(
        """INSERT INTO invoices (org_id, document_id, filename, raw_text, document_type, supplier_name,
               supplier_gstin, invoice_number, invoice_date, currency, subtotal, cgst, sgst, igst, round_off,
               total, bank_account, ifsc, po_number, notes, line_items_json, warnings_json, needs_review,
               review_reasons_json, required_approvals, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            org_id, document_id, filename, raw_text, inv.document_type, inv.supplier_name, inv.supplier_gstin,
            inv.invoice_number, inv.invoice_date.isoformat() if inv.invoice_date else None, inv.currency,
            inv.subtotal, inv.cgst, inv.sgst, inv.igst, inv.round_off, inv.total, inv.bank_account, inv.ifsc,
            inv.po_number, inv.notes, json.dumps([asdict(i) for i in inv.line_items]), json.dumps(warnings),
            int(needs_review), json.dumps(review_reasons), required_approvals, status,
        ),
    )
    invoice_id = cur.lastrowid
    for r in responses:
        conn.execute(
            "INSERT INTO llm_calls (invoice_id, document_id, model, input_tokens, output_tokens, cost_usd, "
            "latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (invoice_id, document_id, r.model, r.input_tokens, r.output_tokens,
             cost_usd(r.model, r.input_tokens, r.output_tokens), r.latency_ms),
        )
    conn.commit()
    return db.get_invoice(conn, invoice_id)
