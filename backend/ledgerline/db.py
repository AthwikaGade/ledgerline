"""SQLite persistence."""
from __future__ import annotations

import json
import sqlite3

from .config import USD_TO_INR

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    filename TEXT,
    raw_text TEXT NOT NULL,
    document_type TEXT,
    supplier_name TEXT,
    supplier_gstin TEXT,
    invoice_number TEXT,
    invoice_date TEXT,
    currency TEXT,
    subtotal REAL,
    cgst REAL,
    sgst REAL,
    igst REAL,
    round_off REAL,
    total REAL,
    bank_account TEXT,
    ifsc TEXT,
    po_number TEXT,
    notes TEXT,
    line_items_json TEXT,
    warnings_json TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reasons_json TEXT,
    required_approvals INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'ready_for_approval',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    user_id TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id),
    document_id TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- AP_POLICY 4.7: who, when, which document, and the note, for every approval and rejection.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    user_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('approve', 'reject')),
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Enforced by the database, not only by the API: AP_POLICY 4.6 (exactly one payment instruction per invoice) and
# 4.2 (one person approving twice counts once). Unique indexes also apply to databases created by the starter.
UNIQUE_INDEXES = [
    ("payments_one_per_invoice", "payments", ("invoice_id",)),
    ("approvals_one_per_person", "approvals", ("invoice_id", "user_id")),
]
BUSY_TIMEOUT_SECONDS = 30  # concurrent writers wait for the lock instead of failing


class MigrationError(RuntimeError):
    """The database holds rows that the new constraints forbid. No rows are changed and the index is not created."""


def _add_unique_indexes(conn: sqlite3.Connection) -> None:
    for name, table, columns in UNIQUE_INDEXES:
        cols = ", ".join(columns)
        duplicates = conn.execute(
            f"SELECT {cols}, COUNT(*) AS n FROM {table} GROUP BY {cols} HAVING COUNT(*) > 1").fetchall()
        if duplicates:
            found = "; ".join(", ".join(f"{c}={row[c]}" for c in columns) + f" ({row['n']} rows)" for row in duplicates)
            raise MigrationError(
                f"Cannot add {name}: table {table} already has duplicate rows for ({cols}): {found}. "
                f"For payments these are real duplicate payment instructions; finance must resolve them before "
                f"Ledgerline can start. No rows were changed and the index was not created.")
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
    conn.commit()


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        _add_unique_indexes(conn)
    except Exception:
        conn.close()
        raise
    return conn


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return None
    inv = dict(row)
    for col in ("line_items_json", "warnings_json", "review_reasons_json"):
        inv[col.removesuffix("_json")] = json.loads(inv.pop(col) or "[]")
    inv["needs_review"] = bool(inv["needs_review"])
    usage = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        "COALESCE(SUM(latency_ms), 0) AS latency_ms FROM llm_calls WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    inv["usage"] = {
        "llm_calls": usage["calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_inr": round(usage["cost_usd"] * USD_TO_INR, 4),
        "latency_ms": usage["latency_ms"],
    }
    return inv
