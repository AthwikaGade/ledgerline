"""Process one document end to end: extract -> normalise -> check -> route -> persist."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from . import db
from .extraction import ExtractionError, extract
from .llm.pricing import cost_usd
from .models import Invoice, LineItem
from .parsing import parse_amount, parse_date
from .reference import ReferenceData
from .validation import run_checks

HIGH_VALUE_THRESHOLD = 500000  # invoices above this need two approvals


def normalize(data: dict) -> Invoice:
    items = [
        LineItem(
            description=str(item.get("description", "")),
            quantity=parse_amount(item.get("quantity")),
            unit_price=parse_amount(item.get("unit_price")),
            amount=parse_amount(item.get("amount")) or 0.0,
        )
        for item in data.get("line_items") or []
    ]
    return Invoice(
        document_type=data.get("document_type") or "invoice",
        supplier_name=data.get("supplier_name"),
        supplier_gstin=data.get("supplier_gstin"),
        invoice_number=data.get("invoice_number"),
        invoice_date=parse_date(data.get("invoice_date")),
        currency=data.get("currency") or "INR",
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


def process_document(
    conn: sqlite3.Connection,
    ref: ReferenceData,
    raw_text: str,
    document_id: str,
    org_id: str = "meridian",
    filename: str | None = None,
) -> dict:
    responses: list = []
    error = None
    try:
        data, responses = extract(raw_text, ref)
        inv = normalize(data)
        warnings = run_checks(conn, ref, inv)
    except ExtractionError as exc:
        responses, error = exc.responses, str(exc)
    except Exception as exc:  # noqa: BLE001 - any failure here must become processing_error, never a dropped doc
        error = f"{type(exc).__name__}: {exc}"

    if error is not None:
        # AP_POLICY 3: processing_error always goes to review and is never dropped. Nothing is invented: every
        # extracted field stays unknown (NULL). required_approvals is a provisional 1; it does not make the
        # document payable, because the approve endpoint refuses documents with an unresolved processing_error.
        inv, data, warnings = _unknown_invoice(), {}, [f"processing_error: {error}"]
        needs_review, review_reasons, required_approvals = True, ["processing_error"], 1
        status = "needs_review"
    else:
        # v0.3: the model applies the AP policy itself (it has the full policy text in its prompt).
        needs_review = bool(data.get("requires_review", False))
        review_reasons = list(data.get("review_reasons") or [])
        required_approvals = 2 if (inv.total or 0) > HIGH_VALUE_THRESHOLD else 1
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
