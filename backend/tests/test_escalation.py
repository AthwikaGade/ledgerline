"""Part 4B: a cheap primary model, with escalation to a stronger model (or another provider) when the primary fails.

Escalation happens only when the primary cannot produce a usable extraction: the call fails (provider error,
outage), the reply is unusable, a critical field is missing or a value is unreadable. A deterministic review reason
is never escalated, and escalation never overrides one (the reasons are the union over every successful read).
"""
import json

import pytest

from ledgerline.llm.base import LLMResponse
from ledgerline.llm.fake import CANNED_EXTRACTION
from ledgerline.pipeline import process_document
from tests.documents import SITARA_DOCUMENT


def extraction(**overrides) -> str:
    return json.dumps(dict(CANNED_EXTRACTION, invoice_date="2026-04-25", **overrides))


class Model:
    def __init__(self, name: str, replies: list[str] | None = None, fail: bool = False):
        self.model, self.replies, self.fail, self.prompts = name, list(replies or []), fail, []

    def complete(self, system, prompt, max_tokens=2000):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("503 provider unavailable")
        return LLMResponse(self.replies.pop(0), self.model, 1_000, 300, 900)


@pytest.fixture
def models(monkeypatch):
    def install(primary: Model, escalation: Model | None):
        monkeypatch.setattr("ledgerline.extraction.get_client", lambda: primary)
        monkeypatch.setattr("ledgerline.extraction.get_escalation_client", lambda: escalation)
        return primary, escalation
    return install


def process(conn, ref, text=SITARA_DOCUMENT):
    return process_document(conn, ref, text, "doc_001")


def test_no_escalation_when_the_primary_extraction_passes(conn, ref, models):
    _, strong = models(Model("claude-haiku-5-5", [extraction()]), Model("claude-opus-5-5", [extraction()]))
    invoice = process(conn, ref)
    assert invoice["review_reasons"] == []
    assert strong.prompts == []
    assert invoice["usage"]["llm_calls"] == 1


def test_unusable_primary_reply_is_escalated(conn, ref, models):
    models(Model("claude-haiku-5-5", ["Sorry, I cannot help."]), Model("claude-opus-5-5", [extraction()]))
    invoice = process(conn, ref)
    assert invoice["review_reasons"] == []
    assert invoice["usage"]["llm_calls"] == 2
    assert any("escalated to claude-opus-5-5" in w for w in invoice["warnings"])


def test_primary_missing_a_critical_field_is_escalated(conn, ref, models):
    models(Model("claude-haiku-5-5", [extraction(total=None)]), Model("claude-opus-5-5", [extraction()]))
    invoice = process(conn, ref)
    assert invoice["review_reasons"] == []
    assert invoice["total"] == 23458.0


def test_provider_outage_falls_back_to_the_other_model(conn, ref, models):
    models(Model("claude-haiku-5-5", fail=True), Model("gpt-backup", [extraction()]))
    invoice = process(conn, ref)
    assert invoice["review_reasons"] == []
    assert any("503 provider unavailable" in w for w in invoice["warnings"])


def test_when_every_model_fails_it_is_a_processing_error(conn, ref, models):
    models(Model("claude-haiku-5-5", fail=True), Model("claude-opus-5-5", fail=True))
    assert process(conn, ref)["review_reasons"] == ["processing_error"]


def test_without_escalation_configured_a_failure_is_a_processing_error(conn, ref, models):
    models(Model("claude-haiku-5-5", ["not json"]), None)
    assert process(conn, ref)["review_reasons"] == ["processing_error"]


@pytest.mark.parametrize("label, overrides, reason", [
    ("totals do not add up", {"total": "23999.00"}, "totals_mismatch"),
    ("GSTIN fails its checksum", {"supplier_gstin": "27AAKCS4821M1ZX"}, "gstin_invalid"),
])
def test_a_policy_failure_goes_to_review_without_escalating(conn, ref, models, label, overrides, reason):
    """A deterministic review reason cannot be cleared by a second reading (escalation never overrides it), so
    escalating would only add cost and latency: in the paid run, dev_008, dev_010 and disp_01 escalated this way
    for ~Rs 1.90 and ~8 s each, and all three still went to review for the same reason."""
    _, strong = models(Model("claude-haiku-5-5", [extraction(**overrides)]), Model("claude-opus-5-5", [extraction()]))
    invoice = process(conn, ref)
    assert reason in invoice["review_reasons"], label
    assert strong.prompts == [], label
    assert invoice["usage"]["llm_calls"] == 1


def test_the_escalation_prompt_is_masked_too(conn, ref, models):
    from tests.test_privacy import assert_no_account_in

    _, strong = models(Model("claude-haiku-5-5", ["not json"]), Model("claude-opus-5-5", [extraction()]))
    process(conn, ref)
    assert strong.prompts
    assert_no_account_in(strong.prompts, SITARA_DOCUMENT, "dev_001")


def test_each_call_is_costed_at_its_own_model_price(conn, ref, models):
    models(Model("claude-haiku-5-5", ["not json"]), Model("claude-opus-5-5", [extraction()]))
    usage = process(conn, ref)["usage"]
    haiku = (1_000 * 0.10 + 300 * 0.50) / 1e6
    opus = (1_000 * 4.00 + 300 * 20.00) / 1e6
    assert usage["cost_inr"] == pytest.approx((haiku + opus) * 88, abs=0.001)


def test_escalation_is_configured_by_environment(monkeypatch):
    from ledgerline.llm import get_escalation_client

    monkeypatch.delenv("LLM_ESCALATION_MODEL", raising=False)
    assert get_escalation_client() is None
    monkeypatch.setenv("LLM_ESCALATION_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("LLM_ESCALATION_PROVIDER", "fake")
    assert get_escalation_client() is not None
