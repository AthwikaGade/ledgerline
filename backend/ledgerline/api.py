"""HTTP API used by the reviewer UI.  Run: uvicorn ledgerline.api:app --reload

Identity is NOT authenticated. `user_id` (in the request body) and the organisation (the `X-Org-Id` header) are
whatever the caller sends. The approval rules below stop the same *name* approving twice; they cannot prove that two
different real people approved. Production use needs authentication (e.g. SSO) to supply both values.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from . import db
from .config import USD_TO_INR, get_settings
from .llm.pricing import PRICES_CHECKED_ON, cost_usd
from .pipeline import process_document
from .reference import load_reference

app = FastAPI(title="Ledgerline API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_conn():
    conn = db.connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_org(x_org_id: str = Header(default="meridian")) -> str:
    return x_org_id


class DecisionRequest(BaseModel):
    user_id: str  # NOT authenticated; see the module docstring
    note: str = ""

    @field_validator("user_id")
    @classmethod
    def _named(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_id is required")
        return value


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """One atomic unit. BEGIN IMMEDIATE takes SQLite's write lock up front, so concurrent decisions on the same
    database run one after another and each re-reads the invoice after the previous one committed. Any exception,
    including an HTTPException refusing the request, rolls back every row written inside the block."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def invoice_in_org(conn: sqlite3.Connection, invoice_id: int, org_id: str) -> sqlite3.Row:
    """Another organisation's invoice is reported as not found, so its existence is not revealed."""
    row = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return row


def audit(conn: sqlite3.Connection, invoice_id: int, user_id: str, action: str, note: str) -> None:
    conn.execute("INSERT INTO audit_log (invoice_id, user_id, action, note) VALUES (?, ?, ?, ?)",
                 (invoice_id, user_id, action, note.strip() or None))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/invoices")
async def upload_invoice(file: UploadFile, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    raw_text = (await file.read()).decode("utf-8")
    document_id = (file.filename or "upload").rsplit(".", 1)[0]
    return process_document(conn, load_reference(), raw_text, document_id, org_id=org_id, filename=file.filename)


@app.get("/api/invoices")
def list_invoices(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT id, document_id, supplier_name, invoice_number, invoice_date, currency, total, status, "
        "needs_review FROM invoices WHERE org_id = ? ORDER BY id DESC",
        (org_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    invoice_in_org(conn, invoice_id, org_id)
    return db.get_invoice(conn, invoice_id)


def _distinct_approvers(conn: sqlite3.Connection, invoice_id: int) -> int:
    return conn.execute("SELECT COUNT(DISTINCT user_id) FROM approvals WHERE invoice_id = ?",
                        (invoice_id,)).fetchone()[0]


@app.post("/api/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: int, body: DecisionRequest, org_id: str = Depends(get_org),
                    conn=Depends(get_conn)):
    """AP_POLICY section 4, enforced inside one transaction. A retry by someone who already approved changes nothing
    and returns 200; the database's unique indexes are the last line of defence against a second payment."""
    with write_transaction(conn):
        invoice = invoice_in_org(conn, invoice_id, org_id)
        reasons = json.loads(invoice["review_reasons_json"] or "[]")
        if "processing_error" in reasons:
            raise HTTPException(status_code=409, detail="This document could not be processed reliably. It cannot "
                                "be approved until it has been extracted and validated successfully.")
        if "duplicate" in reasons:  # 4.4: duplicates can be rejected, never approved
            raise HTTPException(status_code=409, detail="This invoice is flagged as a duplicate and cannot be "
                                "approved.")
        if invoice["document_type"] == "credit_note":  # 2 and 4.1: credit notes are never approved for payment
            raise HTTPException(status_code=409, detail="Credit notes are never approved for payment.")
        if invoice["status"] == "rejected":
            raise HTTPException(status_code=409, detail="This invoice has been rejected.")
        already_approved_by_user = conn.execute(
            "SELECT 1 FROM approvals WHERE invoice_id = ? AND user_id = ?", (invoice_id, body.user_id)).fetchone()
        if invoice["status"] == "approved" and not already_approved_by_user:
            raise HTTPException(status_code=409, detail="This invoice is already approved.")
        if invoice["needs_review"] and not body.note.strip() and not already_approved_by_user:
            raise HTTPException(status_code=422, detail="A note is required to approve a document that needed "
                                "review (AP_POLICY 4.5).")
        inserted = conn.execute(
            "INSERT INTO approvals (invoice_id, user_id, note) VALUES (?, ?, ?) "
            "ON CONFLICT (invoice_id, user_id) DO NOTHING", (invoice_id, body.user_id, body.note)).rowcount
        if inserted:
            audit(conn, invoice_id, body.user_id, "approve", body.note)
        approvals = _distinct_approvers(conn, invoice_id)
        status = invoice["status"]
        if approvals >= invoice["required_approvals"]:
            changed = conn.execute(
                "UPDATE invoices SET status = 'approved' WHERE id = ? AND status IN "
                "('ready_for_approval', 'needs_review')", (invoice_id,)).rowcount
            if changed == 1:  # only the request that completes the approval creates the payment instruction
                conn.execute("INSERT INTO payments (invoice_id, amount) VALUES (?, ?) "
                             "ON CONFLICT (invoice_id) DO NOTHING", (invoice_id, invoice["total"]))
            status = "approved"
    return {"id": invoice_id, "approvals": approvals, "required_approvals": invoice["required_approvals"],
            "status": status}


@app.post("/api/invoices/{invoice_id}/reject")
def reject_invoice(invoice_id: int, body: DecisionRequest, org_id: str = Depends(get_org),
                   conn=Depends(get_conn)):
    """Rejection is final and audited. An approved invoice cannot be rejected: its payment instruction exists."""
    with write_transaction(conn):
        invoice = invoice_in_org(conn, invoice_id, org_id)
        if invoice["status"] == "approved":
            raise HTTPException(status_code=409, detail="This invoice is already approved and its payment "
                                "instruction has been created; it cannot be rejected here.")
        if invoice["status"] != "rejected":
            conn.execute("UPDATE invoices SET status = 'rejected' WHERE id = ? AND status != 'approved'",
                         (invoice_id,))
            audit(conn, invoice_id, body.user_id, "reject", body.note)
    return {"id": invoice_id, "status": "rejected"}


@app.get("/api/stats")
def stats(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    """Feeds the cost dashboard. Costs are ESTIMATES recomputed from recorded token usage at the current verified
    prices (so rows stored with the starter's wrong prices are corrected); the provider's invoice is the actual bill."""
    invoices = conn.execute(
        "SELECT COUNT(DISTINCT c.invoice_id) FROM llm_calls c JOIN invoices i ON i.id = c.invoice_id "
        "WHERE i.org_id = ?", (org_id,)).fetchone()[0]
    by_model = conn.execute(
        "SELECT c.model, COUNT(*) AS calls, COALESCE(SUM(c.input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(c.output_tokens), 0) AS output_tokens "
        "FROM llm_calls c JOIN invoices i ON i.id = c.invoice_id WHERE i.org_id = ? GROUP BY c.model",
        (org_id,)).fetchall()
    total_usd, unpriced = 0.0, 0
    for row in by_model:
        usd = cost_usd(row["model"], row["input_tokens"], row["output_tokens"])
        if usd is None:
            unpriced += row["calls"]
        else:
            total_usd += usd
    total_inr = total_usd * USD_TO_INR
    return {
        "invoices_processed": invoices,
        "llm_calls": sum(row["calls"] for row in by_model),
        "llm_cost_inr": round(total_inr, 2),
        "avg_llm_cost_per_invoice_inr": round(total_inr / invoices, 4) if invoices else 0.0,
        "unpriced_llm_calls": unpriced,
        "cost_basis": (f"Estimated from recorded token usage at list prices checked {PRICES_CHECKED_ON}, converted at "
                       f"Rs {USD_TO_INR:g}/USD. Not the provider's invoice; calls to unpriced models are excluded."),
    }
