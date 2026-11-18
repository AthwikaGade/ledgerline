"""Fix 4: approvals and payment instructions (AP_POLICY section 4), enforced on the server and in the database.

Reproduced against SQLite before this fix: a double-click created two payment instructions, eight simultaneous
approvals created eight, one person could approve a two-approval invoice alone, credit notes and rejected
invoices were approved and paid, and rejections left no audit record.
"""
import json
import sqlite3
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ledgerline import db
from ledgerline.api import DecisionRequest, app, approve_invoice
from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("LEDGERLINE_DB", path)
    client = TestClient(app)

    def upload(number="0101", **overrides):
        data = dict(CANNED_EXTRACTION, invoice_date="2026-04-25", invoice_number=f"SIS/26-27/{number}", **overrides)
        monkeypatch.setattr("ledgerline.extraction.get_client", lambda: FakeClient([json.dumps(data)] * 2))
        response = client.post("/api/invoices", files={"file": (f"{number}.txt", number.encode(), "text/plain")})
        return response.json()

    client.upload = upload
    client.db_path = path
    return client


def approve(api, invoice_id, user="kavya", note="checked against PO"):
    return api.post(f"/api/invoices/{invoice_id}/approve", json={"user_id": user, "note": note})


def reject(api, invoice_id, user="farhan", note="wrong PO"):
    return api.post(f"/api/invoices/{invoice_id}/reject", json={"user_id": user, "note": note})


def count(api, table, invoice_id):
    conn = db.connect(api.db_path)
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE invoice_id = ?", (invoice_id,)).fetchone()[0]


def status(api, invoice_id):
    return api.get(f"/api/invoices/{invoice_id}").json()["status"]


USD = {"currency": "USD", "supplier_gstin": None, "supplier_name": "CloudNimbus Inc.", "bank_account": None,
       "ifsc": None}


# --- Exactly one payment instruction (4.6) ------------------------------------------------------------------------

def test_double_click_records_one_approval_and_one_payment(api):
    invoice = api.upload()
    first, second = approve(api, invoice["id"]), approve(api, invoice["id"])
    assert first.status_code == 200 and second.status_code == 200  # the retry is harmless, not an error
    assert count(api, "approvals", invoice["id"]) == 1
    assert count(api, "payments", invoice["id"]) == 1


def test_another_approver_on_an_approved_invoice_creates_no_second_payment(api):
    invoice = api.upload()
    approve(api, invoice["id"], user="kavya")
    late = approve(api, invoice["id"], user="farhan")
    assert late.status_code == 409
    assert count(api, "payments", invoice["id"]) == 1


def test_concurrent_approvals_create_exactly_one_payment(api):
    """Eight approvers press Approve at the same moment, each request on its own database connection."""
    invoice = api.upload()
    barrier, outcomes = threading.Barrier(8), []

    def press(i):
        conn = db.connect(api.db_path)
        barrier.wait()
        try:
            outcomes.append(approve_invoice(invoice["id"], DecisionRequest(user_id=f"user{i}", note="ok"),
                                            org_id="meridian", conn=conn)["status"])
        except HTTPException as exc:
            outcomes.append(exc.status_code)
        finally:
            conn.close()

    threads = [threading.Thread(target=press, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert count(api, "payments", invoice["id"]) == 1
    assert set(outcomes) <= {"approved", 409}  # no 500s, no database-locked errors
    assert outcomes.count("approved") >= 1


def test_the_database_itself_refuses_a_second_payment_instruction(api):
    invoice = api.upload()
    conn = db.connect(api.db_path)
    conn.execute("INSERT INTO payments (invoice_id, amount) VALUES (?, ?)", (invoice["id"], 23458.0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO payments (invoice_id, amount) VALUES (?, ?)", (invoice["id"], 23458.0))


# --- Distinct approvers (4.2) -------------------------------------------------------------------------------------

def test_one_person_approving_twice_counts_once(api):
    invoice = api.upload(**USD)
    assert invoice["required_approvals"] == 2
    approve(api, invoice["id"], user="kavya")
    approve(api, invoice["id"], user="kavya")
    assert status(api, invoice["id"]) != "approved"
    assert count(api, "payments", invoice["id"]) == 0
    approve(api, invoice["id"], user="farhan")
    assert status(api, invoice["id"]) == "approved"
    assert count(api, "payments", invoice["id"]) == 1


def test_the_database_itself_refuses_the_same_approver_twice(api):
    invoice = api.upload()
    conn = db.connect(api.db_path)
    conn.execute("INSERT INTO approvals (invoice_id, user_id, note) VALUES (?, 'kavya', 'a')", (invoice["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO approvals (invoice_id, user_id, note) VALUES (?, 'kavya', 'b')", (invoice["id"],))


@pytest.mark.parametrize("user", ["", "   "])
def test_an_approval_needs_a_named_approver(api, user):
    invoice = api.upload()
    assert approve(api, invoice["id"], user=user).status_code == 422
    assert count(api, "payments", invoice["id"]) == 0


# --- What can never be approved -----------------------------------------------------------------------------------

def test_a_credit_note_cannot_be_approved_or_paid(api):
    """AP_POLICY 2 and 4.1: credit notes are never approved for payment."""
    invoice = api.upload(document_type="credit_note")
    assert approve(api, invoice["id"]).status_code == 409
    assert count(api, "payments", invoice["id"]) == 0
    assert status(api, invoice["id"]) != "approved"


def test_a_rejected_invoice_cannot_then_be_approved(api):
    invoice = api.upload()
    reject(api, invoice["id"])
    assert approve(api, invoice["id"]).status_code == 409
    assert status(api, invoice["id"]) == "rejected"
    assert count(api, "payments", invoice["id"]) == 0


def test_an_approved_invoice_cannot_then_be_rejected(api):
    """Its payment instruction has already been created; reversing it is a treasury action, not a click."""
    invoice = api.upload()
    approve(api, invoice["id"])
    assert reject(api, invoice["id"]).status_code == 409
    assert status(api, invoice["id"]) == "approved"


# --- Reviewer notes (4.5) -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("note", ["", "   "])
def test_approving_an_invoice_that_needed_review_requires_a_note(api, note):
    invoice = api.upload(cgst="0.00", sgst="0.00", igst="3578.40")  # tax_type_mismatch
    assert invoice["needs_review"] is True
    assert approve(api, invoice["id"], note=note).status_code == 422
    assert count(api, "approvals", invoice["id"]) == 0
    assert approve(api, invoice["id"], note="Vendor confirmed IGST in error; credit note to follow").status_code == 200
    assert count(api, "payments", invoice["id"]) == 1


def test_a_clean_invoice_can_be_approved_without_a_note(api):
    invoice = api.upload()
    assert approve(api, invoice["id"], note="").status_code == 200


# --- Audit log (4.7) ----------------------------------------------------------------------------------------------

def test_approvals_and_rejections_are_recorded_in_the_audit_log(api):
    approved, rejected = api.upload("0201"), api.upload("0202")
    approve(api, approved["id"], user="kavya", note="matches GRN")
    reject(api, rejected["id"], user="farhan", note="wrong PO")
    conn = db.connect(api.db_path)
    rows = [dict(r) for r in conn.execute(
        "SELECT invoice_id, user_id, action, note, created_at FROM audit_log ORDER BY id")]
    assert [(r["invoice_id"], r["user_id"], r["action"], r["note"]) for r in rows] == [
        (approved["id"], "kavya", "approve", "matches GRN"),
        (rejected["id"], "farhan", "reject", "wrong PO"),
    ]
    assert all(r["created_at"] for r in rows)


def test_a_rejection_without_a_note_is_still_audited(api):
    invoice = api.upload()
    assert reject(api, invoice["id"], note="").status_code == 200
    conn = db.connect(api.db_path)
    rows = conn.execute("SELECT user_id, action, note FROM audit_log WHERE invoice_id = ?", (invoice["id"],))
    assert [tuple(r) for r in rows] == [("farhan", "reject", None)]


# --- Organisation boundaries ----------------------------------------------------------------------------------------

OTHER_ORG = {"x-org-id": "another-client"}


def test_another_organisation_cannot_see_an_invoice(api):
    invoice = api.upload()
    assert api.get(f"/api/invoices/{invoice['id']}", headers=OTHER_ORG).status_code == 404


def test_another_organisation_cannot_approve_an_invoice(api):
    invoice = api.upload()
    response = api.post(f"/api/invoices/{invoice['id']}/approve", headers=OTHER_ORG,
                        json={"user_id": "mallory", "note": "ok"})
    assert response.status_code == 404
    assert count(api, "approvals", invoice["id"]) == 0
    assert count(api, "payments", invoice["id"]) == 0


def test_another_organisation_cannot_reject_an_invoice(api):
    invoice = api.upload()
    response = api.post(f"/api/invoices/{invoice['id']}/reject", headers=OTHER_ORG,
                        json={"user_id": "mallory", "note": "x"})
    assert response.status_code == 404
    assert status(api, invoice["id"]) == "ready_for_approval"


# --- Atomicity: a failed transaction leaves nothing behind -----------------------------------------------------------

def fail_inserts_into(path, table):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TRIGGER fail_{table} BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'injected'); END")
    conn.commit()
    conn.close()


def test_a_failure_while_creating_the_payment_rolls_back_the_whole_approval(api):
    invoice = api.upload()
    fail_inserts_into(api.db_path, "payments")
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/invoices/{invoice['id']}/approve", json={"user_id": "kavya", "note": "ok"})
    assert response.status_code == 500
    assert status(api, invoice["id"]) == "ready_for_approval"
    assert count(api, "approvals", invoice["id"]) == 0
    assert count(api, "payments", invoice["id"]) == 0
    assert count(api, "audit_log", invoice["id"]) == 0


def test_a_failure_while_auditing_rolls_back_the_rejection(api):
    invoice = api.upload()
    fail_inserts_into(api.db_path, "audit_log")
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/invoices/{invoice['id']}/reject", json={"user_id": "farhan", "note": "x"})
    assert response.status_code == 500
    assert status(api, invoice["id"]) == "ready_for_approval"


# --- Migrations -------------------------------------------------------------------------------------------------------

def indexes(path):
    conn = sqlite3.connect(path)
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('index', 'table')")}


def starter_database(path, payments_for_invoice_1: int):
    """A database created by the starter: same tables, no unique indexes, no audit_log."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, document_id TEXT NOT NULL,
            filename TEXT, raw_text TEXT NOT NULL, document_type TEXT, supplier_name TEXT, supplier_gstin TEXT,
            invoice_number TEXT, invoice_date TEXT, currency TEXT, subtotal REAL, cgst REAL, sgst REAL, igst REAL,
            round_off REAL, total REAL, bank_account TEXT, ifsc TEXT, po_number TEXT, notes TEXT,
            line_items_json TEXT, warnings_json TEXT, needs_review INTEGER NOT NULL DEFAULT 0,
            review_reasons_json TEXT, required_approvals INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'ready_for_approval', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL, user_id TEXT NOT NULL,
            note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE payments (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL, amount REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO invoices (org_id, document_id, raw_text, status) VALUES ('meridian', 'dev_001', 'x', 'approved');
    """)
    for _ in range(payments_for_invoice_1):
        conn.execute("INSERT INTO payments (invoice_id, amount) VALUES (1, 23458.0)")
    conn.commit()
    conn.close()


def test_a_fresh_database_gets_the_constraints_and_the_audit_log(tmp_path):
    path = str(tmp_path / "fresh.db")
    db.connect(path).close()
    assert {"payments_one_per_invoice", "approvals_one_per_person", "audit_log"} <= indexes(path)


def test_an_existing_clean_database_is_migrated(tmp_path):
    path = str(tmp_path / "starter.db")
    starter_database(path, payments_for_invoice_1=1)
    db.connect(path).close()
    assert {"payments_one_per_invoice", "approvals_one_per_person", "audit_log"} <= indexes(path)


def test_existing_duplicate_payments_stop_the_migration_with_a_clear_error(tmp_path):
    """Two payment instructions for one invoice are a real double payment: refuse to start, change nothing."""
    path = str(tmp_path / "starter.db")
    starter_database(path, payments_for_invoice_1=2)
    with pytest.raises(RuntimeError, match=r"payments.*invoice_id=1"):
        db.connect(path)
    assert "payments_one_per_invoice" not in indexes(path)
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 2
