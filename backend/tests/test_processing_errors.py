"""Fix 1: model responses that are not bare JSON, and documents Ledgerline cannot process.

AP_POLICY section 3, `processing_error`: "These documents always go to review. They are never skipped or dropped."
OUTPUT_CONTRACT: "Never skip a document. If you can't process one reliably, still write its line, with
needs_review: true and "processing_error" among its reasons."

The two fixtures are real, unedited Claude Opus 5.5 responses for dev_001, recorded during the baseline run
(submission/baseline). Opus wraps its JSON in a Markdown fence and adds prose around it.
"""
import json
from pathlib import Path

from ledgerline import cli
from ledgerline.llm.fake import FakeClient
from ledgerline.pipeline import process_document

FIXTURES = Path(__file__).parent / "fixtures"
OPUS_EXTRACT = (FIXTURES / "opus55_dev_001_call1_extract.txt").read_text(encoding="utf-8")
OPUS_VERIFY = (FIXTURES / "opus55_dev_001_call2_verify.txt").read_text(encoding="utf-8")


class FailingClient:
    """A provider that is down, out of credit, or rate limited."""

    model = "fake"

    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt, max_tokens=2000):
        self.calls += 1
        raise RuntimeError("provider unavailable")


def use(monkeypatch, client):
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)
    return client


def test_recorded_opus_response_with_fence_and_prose_is_parsed(conn, ref, monkeypatch):
    use(monkeypatch, FakeClient([OPUS_EXTRACT, OPUS_VERIFY]))
    invoice = process_document(conn, ref, "INVOICE TEXT", "dev_001")
    assert invoice["supplier_gstin"] == "27AAKCS4821M1ZW"
    assert invoice["invoice_number"] == "SIS/26-27/0042"
    assert invoice["total"] == 23458.0
    assert "processing_error" not in invoice["review_reasons"]


def test_unparseable_response_goes_to_review_as_processing_error(conn, ref, monkeypatch):
    use(monkeypatch, FakeClient(["Sorry, I can't read this document."] * 2))
    invoice = process_document(conn, ref, "INVOICE TEXT", "doc_bad")
    assert invoice["needs_review"] is True
    assert "processing_error" in invoice["review_reasons"]
    assert invoice["status"] == "needs_review"


def test_provider_failure_goes_to_review_as_processing_error(conn, ref, monkeypatch):
    use(monkeypatch, FailingClient())
    invoice = process_document(conn, ref, "INVOICE TEXT", "doc_down")
    assert invoice["needs_review"] is True
    assert "processing_error" in invoice["review_reasons"]


def test_calls_made_for_a_failed_document_are_still_recorded(conn, ref, monkeypatch):
    """Spend on documents that fail must reach llm_calls, or the cost dashboard under-reports the bill."""
    use(monkeypatch, FakeClient(["not json"] * 2))
    invoice = process_document(conn, ref, "INVOICE TEXT", "doc_bad")
    assert invoice["usage"]["llm_calls"] >= 1


def test_failed_document_is_stored_without_invented_values(conn, ref, monkeypatch):
    """Nothing the model did not reliably give us may be filled in: no amounts, no date, no currency."""
    use(monkeypatch, FakeClient(["not json"] * 2))
    invoice = process_document(conn, ref, "INVOICE TEXT", "doc_bad")
    row = dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice["id"],)).fetchone())
    for column in ("subtotal", "cgst", "sgst", "igst", "round_off", "total", "currency", "invoice_date",
                   "supplier_gstin", "invoice_number", "bank_account", "ifsc"):
        assert row[column] is None, column
    assert row["raw_text"] == "INVOICE TEXT"  # AP_POLICY 5.3: keep the original document
    assert any("processing_error" in w for w in json.loads(row["warnings_json"]))  # why, for the reviewer


def test_unresolved_processing_error_never_creates_a_payment(tmp_path, monkeypatch):
    """Going to review is not enough: the invoice must not become payable while its fields are unknown."""
    from fastapi.testclient import TestClient

    from ledgerline.api import app

    monkeypatch.setenv("LEDGERLINE_DB", str(tmp_path / "api.db"))
    use(monkeypatch, FakeClient(["not json"] * 2))
    client = TestClient(app)
    invoice_id = client.post("/api/invoices", files={"file": ("bad.txt", b"text", "text/plain")}).json()["id"]

    response = client.post(f"/api/invoices/{invoice_id}/approve", json={"user_id": "kavya", "note": "looks fine"})

    assert response.status_code == 409
    assert client.get(f"/api/invoices/{invoice_id}").json()["status"] == "needs_review"
    from ledgerline import db
    conn = db.connect(str(tmp_path / "api.db"))
    assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


CONTRACT_FIELDS = ["document_id", "document_type", "supplier_name", "supplier_gstin", "invoice_number",
                   "invoice_date", "currency", "subtotal", "cgst", "sgst", "igst", "round_off", "total",
                   "bank_account", "ifsc", "po_number", "line_items", "needs_review", "review_reasons",
                   "required_approvals", "usage"]
USAGE_FIELDS = {"llm_calls", "input_tokens", "output_tokens", "cost_inr", "latency_ms"}


def assert_processing_error_line(line):
    """Every OUTPUT_CONTRACT field present; unknown values are null, never invented."""
    assert set(CONTRACT_FIELDS) <= set(line)  # JSON key order carries no meaning; the fields must all be there
    assert line["document_type"] in ("invoice", "credit_note")
    for field in ("supplier_gstin", "invoice_date", "currency", "subtotal", "cgst", "sgst", "igst",
                  "round_off", "total", "bank_account", "ifsc"):
        assert line[field] is None, field
    assert line["line_items"] == []
    assert line["needs_review"] is True
    assert "processing_error" in line["review_reasons"]
    assert line["required_approvals"] == 1  # provisional; the document is not payable until resolved
    assert set(line["usage"]) == USAGE_FIELDS


def run_batch(tmp_path, files: dict[str, bytes]) -> list[dict]:
    folder = tmp_path / "in"
    folder.mkdir()
    for name, content in files.items():
        (folder / name).write_bytes(content)
    out = tmp_path / "predictions.jsonl"
    cli.main(["predict", "--input", str(folder), "--reference", str(Path(__file__).parents[2] / "data" / "reference"),
              "--output", str(out)])
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def test_batch_line_for_a_failed_document_meets_the_output_contract(tmp_path, monkeypatch):
    use(monkeypatch, FakeClient(["not json"] * 2))
    [line] = run_batch(tmp_path, {"bad_001.txt": b"some document"})
    assert_processing_error_line(line)
    assert line["usage"]["llm_calls"] >= 1  # the spend on this document is reported, not lost


def test_batch_does_not_skip_a_file_that_is_not_valid_utf8(tmp_path, monkeypatch):
    use(monkeypatch, FakeClient())
    lines = run_batch(tmp_path, {"enc_001.txt": b"\xff\xfe\x00 invoice in UTF-16?"})
    assert [line["document_id"] for line in lines] == ["enc_001"]
    assert_processing_error_line(lines[0])


def test_batch_never_skips_a_document(tmp_path, monkeypatch):
    use(monkeypatch, FakeClient(["not json"] * 10))
    folder = tmp_path / "in"
    folder.mkdir()
    for name in ("a_001.txt", "a_002.eml", "a_003.json"):
        (folder / name).write_text("some document", encoding="utf-8")
    out = tmp_path / "predictions.jsonl"
    cli.main(["predict", "--input", str(folder), "--reference", str(Path(__file__).parents[2] / "data" / "reference"),
              "--output", str(out)])
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [line["document_id"] for line in lines] == ["a_001", "a_002", "a_003"]
    assert all(line["needs_review"] and "processing_error" in line["review_reasons"] for line in lines)
