"""Fix 6: LLM cost reporting.

The CTO's October bill was about $165; Ledgerline's dashboard said Rs 15 for the month. The price table was labelled
"USD per million tokens" but held prices per thousand tokens, so every cost was 1,000 times too low
($165 x 88 / 1,000 = Rs 14.5). Unknown models were silently priced at zero.

These tests are about reporting the cost accurately. Whether the cost meets the Rs 1.50 per document target is a
separate question, answered in EVAL_REPORT.md.
"""
import json

import pytest
from fastapi.testclient import TestClient

from ledgerline.api import app
from ledgerline.config import USD_TO_INR
from ledgerline.llm.base import LLMResponse
from ledgerline.llm.fake import CANNED_EXTRACTION
from ledgerline.llm.pricing import cost_usd
from ledgerline.pipeline import process_document


@pytest.mark.parametrize("model, input_price, output_price", [
    ("claude-opus-5-5", 4.00, 20.00), ("claude-sonnet-5-5", 2.00, 10.00), ("claude-haiku-5-5", 0.10, 0.50)])
def test_prices_are_usd_per_million_tokens(model, input_price, output_price):
    """Anthropic list prices, checked 18 Nov 2026."""
    assert cost_usd(model, 1_000_000, 0) == pytest.approx(input_price)
    assert cost_usd(model, 0, 1_000_000) == pytest.approx(output_price)


def test_recorded_baseline_usage_reproduces_what_was_billed():
    """Run A of the baseline (unchanged starter, Opus 5.5, 30 calls) used 265,475 input and 61,526 output tokens,
    recorded from the provider's own usage fields; at list prices that is $2.2924 (submission/baseline)."""
    assert cost_usd("claude-opus-5-5", 265_475, 61_526) == pytest.approx(2.2924, abs=0.0001)


def test_one_recorded_opus_call_costs_what_the_provider_charges():
    """dev_001's extraction call: 8,970 input + 2,021 output tokens = $0.0359 + $0.0404."""
    assert cost_usd("claude-opus-5-5", 8_970, 2_021) == pytest.approx(0.07630, abs=0.00001)


def test_an_unknown_model_is_reported_as_unpriced_not_free():
    assert cost_usd("some-future-model", 1_000, 1_000) is None


class FixedUsageModel:
    """Returns a clean extraction with the token usage of a real Opus 5.5 call."""

    model = "claude-opus-5-5"

    def complete(self, system, prompt, max_tokens=2000):
        data = dict(CANNED_EXTRACTION, invoice_date="2026-04-25")
        return LLMResponse(json.dumps(data), self.model, 8_970, 2_021, 18_000)


EXPECTED_PER_DOCUMENT_USD = 0.0763  # one extraction call per document (the starter made two)


def test_per_document_usage_reports_the_real_cost(conn, ref, monkeypatch):
    monkeypatch.setattr("ledgerline.extraction.get_client", FixedUsageModel)
    invoice = process_document(conn, ref, "INVOICE TEXT", "doc_001")
    assert invoice["usage"]["cost_inr"] == pytest.approx(EXPECTED_PER_DOCUMENT_USD * USD_TO_INR, abs=0.01)


def test_the_dashboard_reports_the_real_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGERLINE_DB", str(tmp_path / "api.db"))
    monkeypatch.setattr("ledgerline.extraction.get_client", FixedUsageModel)
    client = TestClient(app)
    for name in ("a.txt", "b.txt", "c.txt"):
        client.post("/api/invoices", files={"file": (name, b"text", "text/plain")})
    stats = client.get("/api/stats").json()
    assert stats["llm_cost_inr"] == pytest.approx(3 * EXPECTED_PER_DOCUMENT_USD * USD_TO_INR, abs=0.05)
    assert stats["avg_llm_cost_per_invoice_inr"] == pytest.approx(EXPECTED_PER_DOCUMENT_USD * USD_TO_INR, abs=0.01)


def test_the_dashboard_says_when_some_calls_could_not_be_priced(tmp_path, monkeypatch):
    class UnknownModel(FixedUsageModel):
        model = "some-future-model"

    monkeypatch.setenv("LEDGERLINE_DB", str(tmp_path / "api.db"))
    monkeypatch.setattr("ledgerline.extraction.get_client", UnknownModel)
    client = TestClient(app)
    client.post("/api/invoices", files={"file": ("a.txt", b"text", "text/plain")})
    assert client.get("/api/stats").json()["unpriced_llm_calls"] == 1  # one call per document
