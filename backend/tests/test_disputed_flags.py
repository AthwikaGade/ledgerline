"""Part 2: the two disputed documents the literal policy routes as ready, and the flagged checks for them.

Rulings: disp_05 (a line whose quantity x rate does not equal its amount: Rs 550 over, Rs 649 with GST) and disp_06
(an invoice dated two months after the email that delivered it, which also takes the vendor out of the 90-day
vendor_new window) should go to review. AP_POLICY.md has no rule for either, so each check is behind a flag that is
off by default, with a new review-reason code (allowed only behind a flag):

    LEDGERLINE_FLAG_LINE_ARITHMETIC=1  ->  line_amount_mismatch
    LEDGERLINE_FLAG_FUTURE_DATED=1     ->  future_dated

The fixtures are real Claude Opus 5.5 responses from the improved pipeline's paid run (the model saw masked numbers,
so they contain none).
"""
import json
from datetime import date
from pathlib import Path

import pytest

from ledgerline.llm.fake import CANNED_EXTRACTION, FakeClient
from ledgerline.pipeline import process_document
from tests.documents import SITARA_DOCUMENT

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


def recorded(doc: str) -> str:
    return (FIXTURES / f"opus55_improved_{doc}.txt").read_text(encoding="utf-8")


def document(doc: str) -> str:
    [path] = (REPO / "data" / "invoices").glob(f"*/{doc}.*")
    return path.read_text(encoding="utf-8")


def run_recorded(conn, ref, monkeypatch, doc: str) -> dict:
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: FakeClient([recorded(doc)]))
    return process_document(conn, ref, document(doc), doc)


def run(conn, ref, monkeypatch, text=SITARA_DOCUMENT, **overrides) -> dict:
    data = {**CANNED_EXTRACTION, "invoice_date": "2026-04-25", **overrides}
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: FakeClient([json.dumps(data)]))
    return process_document(conn, ref, text, "doc")


@pytest.fixture(autouse=True)
def fixed_processing_date(monkeypatch):
    """Comparisons with the processing date are deterministic: 'today' is 18 Nov 2026 in every test here."""
    monkeypatch.setattr("ledgerline.validation.today", lambda: date(2026, 11, 18), raising=False)


@pytest.fixture
def no_flags(monkeypatch):
    for name in ("LINE_ARITHMETIC", "FUTURE_DATED"):
        monkeypatch.delenv(f"LEDGERLINE_FLAG_{name}", raising=False)


@pytest.fixture
def flags_on(monkeypatch):
    monkeypatch.setenv("LEDGERLINE_FLAG_LINE_ARITHMETIC", "1")
    monkeypatch.setenv("LEDGERLINE_FLAG_FUTURE_DATED", "1")


# --- Step 0: quantities copied with their unit must not break extraction ------------------------------------------

def test_quantities_printed_with_a_unit_are_read_not_rejected(conn, ref, monkeypatch, no_flags):
    """Opus returned '12 BOX' and '4 PKT' for dev_001; the starter's float() raised and the clean invoice became a
    processing_error. Quantity is not used by any policy rule, so its number is read leniently."""
    invoice = run_recorded(conn, ref, monkeypatch, "dev_001")
    assert invoice["review_reasons"] == []
    assert [item["quantity"] for item in invoice["line_items"]] == [12.0, 4.0]


@pytest.mark.parametrize("printed, expected", [("12 BOX", 12.0), ("340 nos", 340.0), ("2,000 kg", 2000.0),
                                               ("2.5 MT", 2.5), ("as agreed", None), (None, None)])
def test_quantity_is_read_leniently(printed, expected):
    from ledgerline.parsing import parse_leading_number

    assert parse_leading_number(printed) == expected


def test_unit_price_stays_strict_and_is_never_guessed(conn, ref, monkeypatch, no_flags):
    """Only quantity is lenient. An unreadable unit price is a processing_error, not a number we made up."""
    item = {"description": "Bolt", "quantity": "12 BOX", "unit_price": "1,450.00/box", "amount": "17,400.00"}
    invoice = run(conn, ref, monkeypatch, line_items=[item])
    assert invoice["review_reasons"] == ["processing_error"]


def test_a_missing_line_amount_never_becomes_zero(conn, ref, monkeypatch, no_flags):
    """A line without an amount means the total cannot be verified: it goes to review, it is not counted as 0."""
    items = [{"description": "Bolt", "quantity": "12", "unit_price": "1,450.00", "amount": "17,400.00"},
             {"description": "Washer", "quantity": "4", "unit_price": "620.00", "amount": None}]
    invoice = run(conn, ref, monkeypatch, line_items=items, total="23458.00")
    assert "totals_mismatch" in invoice["review_reasons"]
    assert invoice["line_items"][1]["amount"] is None


# --- disp_05: line arithmetic ------------------------------------------------------------------------------------

def test_disp_05_is_ready_with_the_flag_off(conn, ref, monkeypatch, no_flags):
    assert run_recorded(conn, ref, monkeypatch, "disp_05")["review_reasons"] == []


def test_disp_05_goes_to_review_with_the_flag_on(conn, ref, monkeypatch, flags_on):
    invoice = run_recorded(conn, ref, monkeypatch, "disp_05")
    assert invoice["review_reasons"] == ["line_amount_mismatch"]
    assert invoice["needs_review"] is True
    assert invoice["required_approvals"] == 1
    assert any("4 x 3850.00 = 15400.00, printed 15950.00" in w for w in invoice["warnings"])


@pytest.mark.parametrize("label, item, flagged", [
    ("exact", {"quantity": "4", "unit_price": "3,850.00", "amount": "15,400.00"}, False),
    ("within Rs 1.00", {"quantity": "3", "unit_price": "33.33", "amount": "100.00"}, False),
    ("Rs 1.01 off", {"quantity": "1", "unit_price": "100.00", "amount": "101.01"}, True),
    ("fractional quantity", {"quantity": "2.5 MT", "unit_price": "100.00", "amount": "250.00"}, False),
    ("unit in quantity", {"quantity": "2,000 kg", "unit_price": "1.12", "amount": "2,240.00"}, False),
    ("no unit price printed: cannot check", {"quantity": "1", "unit_price": None, "amount": "500.00"}, False),
])
def test_line_arithmetic_rule(conn, ref, monkeypatch, flags_on, label, item, flagged):
    amount = item["amount"]
    invoice = run(conn, ref, monkeypatch, line_items=[dict(item, description="Item")], subtotal=amount,
                  cgst="0.00", sgst="0.00", round_off="0.00", total=amount)
    assert "processing_error" not in invoice["review_reasons"], label  # the line was read, not rejected
    assert ("line_amount_mismatch" in invoice["review_reasons"]) is flagged, label


# --- disp_06: future-dated invoices --------------------------------------------------------------------------------

def test_disp_06_is_ready_with_the_flag_off(conn, ref, monkeypatch, no_flags):
    assert run_recorded(conn, ref, monkeypatch, "disp_06")["review_reasons"] == []


def test_disp_06_goes_to_review_with_the_flag_on(conn, ref, monkeypatch, flags_on):
    invoice = run_recorded(conn, ref, monkeypatch, "disp_06")
    assert invoice["review_reasons"] == ["future_dated"]
    assert invoice["invoice_date"] == "2026-06-25"  # the printed date is still the document date (AP_POLICY 1)
    note = next(w for w in invoice["warnings"] if "2026-06-25" in w)
    assert "2026-04-28" in note and "Date header" in note and "sender-supplied" in note


EMAIL = "From: a@b.example\nTo: ap@meridian-precision.example\nDate: Tue, 28 Apr 2026 12:05:00 +0530\n\nInvoice body\n"


@pytest.mark.parametrize("invoice_date, flagged", [("2026-04-27", False), ("2026-04-28", False),
                                                   ("2026-04-29", True)])
def test_invoice_dated_after_the_email_that_delivered_it(conn, ref, monkeypatch, flags_on, invoice_date, flagged):
    text = EMAIL + SITARA_DOCUMENT
    invoice = run(conn, ref, monkeypatch, text=text, invoice_date=invoice_date)
    assert ("future_dated" in invoice["review_reasons"]) is flagged


@pytest.mark.parametrize("invoice_date, flagged", [("2026-11-18", False), ("2026-11-19", True)])
def test_a_scanned_invoice_dated_after_the_day_it_is_processed(conn, ref, monkeypatch, flags_on, invoice_date,
                                                              flagged):
    """No email header: the only bound is the processing date (a document cannot be received after it is
    processed). 'today' is fixed to 18 Nov 2026 by the autouse fixture."""
    invoice = run(conn, ref, monkeypatch, invoice_date=invoice_date)
    assert ("future_dated" in invoice["review_reasons"]) is flagged
    if flagged:
        assert any("processed" in w for w in invoice["warnings"])


def test_an_email_date_header_is_only_read_from_the_header_block(conn, ref, monkeypatch, flags_on):
    """A 'Date:' line in the body (or on a scanned invoice) is not an email header."""
    text = SITARA_DOCUMENT + "\nDate: Tue, 01 Jan 2019 10:00:00 +0530\n"
    assert "future_dated" not in run(conn, ref, monkeypatch, text=text)["review_reasons"]


# --- Contract and defaults ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_flags_are_on_only_when_set_to_1(conn, ref, monkeypatch, value):
    monkeypatch.setenv("LEDGERLINE_FLAG_LINE_ARITHMETIC", value)
    monkeypatch.setenv("LEDGERLINE_FLAG_FUTURE_DATED", value)
    assert run_recorded(conn, ref, monkeypatch, "disp_05")["review_reasons"] == []


def test_new_codes_are_reported_after_the_policy_codes(conn, ref, monkeypatch, flags_on):
    """Both flags can apply together with policy codes; every applicable reason is still returned."""
    from ledgerline.validation import REASON_ORDER

    assert REASON_ORDER[-2:] == ["line_amount_mismatch", "future_dated"]
    invoice = run(conn, ref, monkeypatch, text=EMAIL + SITARA_DOCUMENT, invoice_date="2026-05-30",
                  bank_account="50200099999999",
                  line_items=[{"description": "x", "quantity": "1", "unit_price": "100.00", "amount": "19880.00"}])
    assert invoice["review_reasons"][-2:] == ["line_amount_mismatch", "future_dated"]
    assert "bank_details_changed" not in invoice["review_reasons"]  # the printed account is still Sitara's
