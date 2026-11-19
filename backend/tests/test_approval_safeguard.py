"""Approvals are refused outside local development until verified authentication exists.

Ledgerline has no authentication yet: the approver's name and organisation are whatever the caller sends (FINDINGS,
"Security"). Until identity and roles come from Meridian's SSO, approve and reject are allowed only when
LEDGERLINE_ENV=development AND the request comes from this machine. Anywhere else (including when LEDGERLINE_ENV is
unset, which counts as production) they return 403. No setting enables them in production.
"""
import json

import pytest
from fastapi.testclient import TestClient

from ledgerline import db
from ledgerline.api import app
from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from tests.documents import SITARA_DOCUMENT

REMOTE = ("203.0.113.7", 50000)  # a documentation-range address: any machine other than this one


@pytest.fixture
def invoice(tmp_path, monkeypatch):
    """A clean invoice, uploaded while in development (uploading is not restricted)."""
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("LEDGERLINE_DB", path)
    monkeypatch.setenv("LEDGERLINE_ENV", "development")
    data = {**CANNED_EXTRACTION, "invoice_date": "2026-04-25"}
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: FakeClient([json.dumps(data)]))
    response = TestClient(app).post("/api/invoices", files={"file": ("a.txt", SITARA_DOCUMENT.encode(), "text/plain")})
    return {"id": response.json()["id"], "db": path}


def decide(client, invoice, action):
    return client.post(f"/api/invoices/{invoice['id']}/{action}", json={"user_id": "kavya", "note": "checked"})


def nothing_recorded(invoice):
    conn = db.connect(invoice["db"])
    counts = [conn.execute(f"SELECT COUNT(*) FROM {t} WHERE invoice_id = ?", (invoice["id"],)).fetchone()[0]
              for t in ("approvals", "payments", "audit_log")]
    status = conn.execute("SELECT status FROM invoices WHERE id = ?", (invoice["id"],)).fetchone()[0]
    return counts == [0, 0, 0] and status == "ready_for_approval"


@pytest.mark.parametrize("environment", [None, "production", "prod", "staging", "", "Development "])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_outside_development_approve_and_reject_are_refused(invoice, monkeypatch, environment, action):
    if environment is None:
        monkeypatch.delenv("LEDGERLINE_ENV", raising=False)  # unset counts as production
    else:
        monkeypatch.setenv("LEDGERLINE_ENV", environment)
    response = decide(TestClient(app), invoice, action)
    assert response.status_code == 403
    assert "authentication" in response.json()["detail"]
    assert nothing_recorded(invoice)


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_in_development_a_request_from_another_machine_is_refused(invoice, action):
    response = decide(TestClient(app, client=REMOTE), invoice, action)
    assert response.status_code == 403
    assert nothing_recorded(invoice)


@pytest.mark.parametrize("override", ["LEDGERLINE_ALLOW_APPROVALS", "LEDGERLINE_AUTH_DISABLED",
                                      "LEDGERLINE_FLAG_APPROVALS", "LEDGERLINE_APPROVALS_ENABLED"])
def test_no_setting_enables_approvals_in_production(invoice, monkeypatch, override):
    monkeypatch.setenv("LEDGERLINE_ENV", "production")
    monkeypatch.setenv(override, "1")
    assert decide(TestClient(app), invoice, "approve").status_code == 403
    assert nothing_recorded(invoice)


def test_local_development_still_approves(invoice):
    response = decide(TestClient(app), invoice, "approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_reading_and_uploading_still_work_in_production(invoice, monkeypatch):
    monkeypatch.setenv("LEDGERLINE_ENV", "production")
    client = TestClient(app, client=REMOTE)
    assert client.get("/api/invoices").status_code == 200
    assert client.get(f"/api/invoices/{invoice['id']}").status_code == 200
    assert client.get("/api/stats").status_code == 200
