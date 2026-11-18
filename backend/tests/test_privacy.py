"""Fix 5: AP_POLICY section 5 (Data Protection Officer).

5.1 Vendor bank account numbers must not be sent to external LLM providers (masking all but the last four digits
    is acceptable). 5.2 Send providers only the data the task needs. 5.3 Keep the original document for audit.

Before this fix every call carried the whole vendor master (37 full account numbers), three few-shot dev documents
with their account numbers, and the document's own account number, unmasked, twice per document.
Bank-change detection must keep working although the model now only ever sees masked numbers.
"""
import json
import re
from pathlib import Path

import pytest

from ledgerline import cli
from ledgerline.llm.base import LLMResponse
from ledgerline.pipeline import process_document

REPO = Path(__file__).resolve().parents[2]
DOCS = sorted((REPO / "data" / "invoices").glob("*/*.*"))
LABELS = {json.loads(line)["document_id"]: json.loads(line)["expected"]
          for line in (REPO / "data" / "ground_truth" / "dev.jsonl").read_text(encoding="utf-8").splitlines()}

# A bank-account-like number: 9 to 18 digits, optionally grouped by single spaces or hyphens, not part of a word.
ACCOUNT_LIKE = re.compile(r"(?<![0-9A-Za-z])\d(?:[ -]?\d){8,17}(?![0-9A-Za-z])")


class RecordingModel:
    """Stands in for the provider. Records every prompt, and answers with the labelled extraction for the document,
    except that bank_account is copied from what the model was actually shown (masked or not)."""

    model = "fake"

    def __init__(self, expected: dict, raw_text: str):
        self.expected, self.raw_text, self.prompts = expected, raw_text, []

    def complete(self, system, prompt, max_tokens=2000):
        self.prompts.append(system + "\n" + prompt)
        answer = dict(self.expected, requires_review=False, review_reasons=[])
        if self.expected.get("bank_account"):
            answer["bank_account"] = self._account_as_shown(prompt)
        return LLMResponse(json.dumps(answer), self.model, 100, 100, 1)

    def _account_as_shown(self, prompt: str) -> str:
        """The account number on the document's bank line, exactly as it appears in the prompt."""
        last4 = re.sub(r"\D", "", self.expected["bank_account"])[-4:]
        shown = re.findall(r"[0-9X][0-9X -]{3,}" + last4, prompt)
        return shown[-1].strip() if shown else ""


def run(monkeypatch, conn, ref, path: Path) -> tuple[dict, RecordingModel]:
    raw = path.read_text(encoding="utf-8")
    expected = LABELS.get(path.stem) or LABELS["dev_001"]
    model = RecordingModel(expected, raw)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: model)
    return process_document(conn, ref, raw, path.stem), model


def known_accounts(raw: str, doc: str) -> set[str]:
    """Every bank account we know of: all of the vendor master, any account on this document, and its label."""
    from ledgerline.bank import find_bank_details
    from ledgerline.reference import load_reference

    accounts = {re.sub(r"\D", "", v["bank_account"]) for v in load_reference().vendors if v.get("bank_account")}
    accounts |= set(find_bank_details(raw).accounts)
    if LABELS.get(doc, {}).get("bank_account"):
        accounts.add(re.sub(r"\D", "", LABELS[doc]["bank_account"]))
    return {a for a in accounts if len(a) >= 9}


# Deliberately stricter than the code's own pattern: ANY 9+ digits in a row (spaces/hyphens allowed between them),
# whatever surrounds them, counts as a possible account number.
ANY_LONG_NUMBER = re.compile(r"\d(?:[ \-]?\d){8,}")


def assert_no_account_in(prompts: list[str], raw: str, doc: str) -> None:
    for account in known_accounts(raw, doc):
        spaced = re.compile(r"[ \-]?".join(account))  # also catches 5020 0012 3456 78 and 5020-0012-...
        assert not any(spaced.search(p) for p in prompts), f"bank account ...{account[-4:]} was sent"
    for prompt in prompts:
        found = ANY_LONG_NUMBER.search(prompt)
        last4 = re.sub(r"\D", "", found.group(0))[-4:] if found else ""
        assert found is None, f"a long number was sent: ...{last4}"  # (no backslash inside the f-string: 3.11)


@pytest.mark.parametrize("path", DOCS, ids=[p.stem for p in DOCS])
def test_no_full_account_number_is_sent_to_the_llm(conn, ref, monkeypatch, path):
    _, model = run(monkeypatch, conn, ref, path)
    assert model.prompts
    assert_no_account_in(model.prompts, path.read_text(encoding="utf-8"), path.stem)


def test_the_vendor_master_is_not_sent(conn, ref, monkeypatch):
    _, model = run(monkeypatch, conn, ref, REPO / "data" / "invoices" / "dev" / "dev_001.txt")
    for prompt in model.prompts:
        assert "vendor_id,legal_name" not in prompt
        assert "Ambica Engineering" not in prompt  # a vendor that does not appear on this document


@pytest.mark.parametrize("doc", ["dev_001", "dev_005", "dev_006", "dev_024"])
def test_bank_change_detection_still_works_on_masked_numbers(conn, ref, monkeypatch, doc):
    """dev_005 and dev_024 show a changed account (labelled bank_details_changed); dev_001 and dev_006 do not."""
    [path] = (REPO / "data" / "invoices" / "dev").glob(f"{doc}.*")
    invoice, model = run(monkeypatch, conn, ref, path)
    assert_no_account_in(model.prompts, path.read_text(encoding="utf-8"), doc)
    assert ("bank_details_changed" in invoice["review_reasons"]) is (
        "bank_details_changed" in LABELS[doc]["review_reasons"])


def test_the_full_number_is_kept_locally_for_audit_and_output(tmp_path, monkeypatch):
    """The contract's bank_account is 'digits as printed'; the database keeps the original (AP_POLICY 5.3)."""
    raw = (REPO / "data" / "invoices" / "dev" / "dev_001.txt").read_text(encoding="utf-8")
    model = RecordingModel(LABELS["dev_001"], raw)
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: model)
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "dev_001.txt").write_text(raw, encoding="utf-8")
    out = tmp_path / "out.jsonl"
    cli.main(["predict", "--input", str(folder), "--reference", str(REPO / "data" / "reference"),
              "--output", str(out)])
    line = json.loads(out.read_text(encoding="utf-8"))
    assert line["bank_account"] == LABELS["dev_001"]["bank_account"]
    assert_no_account_in(model.prompts, raw, "dev_001")


def answering(monkeypatch, answer: dict):
    class Model:
        model = "fake"

        def complete(self, system, prompt, max_tokens=2000):
            return LLMResponse(json.dumps(answer), self.model, 1, 1, 1)

    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: Model())


DEV_001 = (REPO / "data" / "invoices" / "dev" / "dev_001.txt").read_text(encoding="utf-8")


def test_the_model_cannot_vouch_for_bank_details(conn, ref, monkeypatch):
    """The model's bank_account is never trusted: dev_001's account is read locally even if the model says otherwise."""
    answering(monkeypatch, dict(LABELS["dev_001"], bank_account="XXXXXXXXXX9999"))
    invoice = process_document(conn, ref, DEV_001, "dev_001")
    assert invoice["bank_account"] == LABELS["dev_001"]["bank_account"]
    assert "bank_details_changed" not in invoice["review_reasons"]


def test_an_account_the_model_saw_but_we_cannot_read_locally_goes_to_review(conn, ref, monkeypatch):
    """Bank details written in a form the local reader does not recognise are unverified, so they are reviewed."""
    raw = DEV_001.replace("A/c No.   :", "Remit to")  # account still printed, but unlabelled
    answering(monkeypatch, dict(LABELS["dev_001"], bank_account="XXXXXXXXXX5678"))
    invoice = process_document(conn, ref, raw, "dev_001")
    assert "bank_details_changed" in invoice["review_reasons"]
    assert any("not verified" in w for w in invoice["warnings"])


def test_two_different_accounts_on_one_document_go_to_review(conn, ref, monkeypatch):
    raw = DEV_001 + "\nPlease use our new A/c No: 50200077770000 from next month.\n"
    answering(monkeypatch, dict(LABELS["dev_001"]))
    invoice = process_document(conn, ref, raw, "dev_001")
    assert "bank_details_changed" in invoice["review_reasons"]


# --- Local, deterministic reading of bank details ----------------------------------------------------------------

DEV_WITH_ACCOUNT = sorted(d for d, e in LABELS.items() if e.get("bank_account"))


@pytest.mark.parametrize("doc", DEV_WITH_ACCOUNT)
def test_local_reader_finds_exactly_the_labelled_account(doc):
    from ledgerline.bank import find_bank_details

    [path] = (REPO / "data" / "invoices" / "dev").glob(f"{doc}.*")
    found = find_bank_details(path.read_text(encoding="utf-8"))
    assert found.accounts == [re.sub(r"\D", "", LABELS[doc]["bank_account"])]
    if LABELS[doc].get("ifsc"):
        assert found.ifscs == [LABELS[doc]["ifsc"].upper()]


# --- Masking must not damage anything else the extraction needs ----------------------------------------------------

@pytest.mark.parametrize("doc", sorted(LABELS))
def test_masking_keeps_every_other_labelled_value_intact(doc):
    """Every labelled value without a long number in it (other than the account) is still printed verbatim."""
    from ledgerline.bank import mask_for_llm

    [path] = (REPO / "data" / "invoices" / "dev").glob(f"{doc}.*")
    raw = path.read_text(encoding="utf-8")
    masked = mask_for_llm(raw)
    for field in ("supplier_name", "supplier_gstin", "invoice_number", "po_number", "ifsc"):
        value = LABELS[doc].get(field)
        if value and value in raw and not ANY_LONG_NUMBER.search(value):
            assert value in masked, field


@pytest.mark.parametrize("path", DOCS, ids=[p.stem for p in DOCS])
def test_masking_is_exactly_reversible_locally(path):
    """Restoring the tokens gives back the original document byte for byte: nothing is corrupted."""
    from ledgerline.bank import restore_tokens, tokenize_for_llm

    raw = path.read_text(encoding="utf-8")
    masked, originals = tokenize_for_llm(raw)
    assert restore_tokens(masked, originals) == raw


# Unknown account numbers (in no vendor master, on no document) under labels that do not say "account".
MISLEADING = ["Invoice Ref: 50200077770000", "PO No: 31840199990000", "Our Ref: 0732201004411 (use for NEFT)",
              "Credit Note No. 5020 0077 7700 00", "Invoice No: INV-918273645546", "Order # 4455-6677-8899-00",
              "Remit to 50200012345678 at Zephyr Bank", "Call 9876543210 for queries", "A/C NO 5020 0012 3456 78",
              '"AccDet": "50200098765432",', "Beneficiary AC91827364554 (Tal Bank)"]


@pytest.mark.parametrize("line", MISLEADING)
def test_no_long_number_survives_masking_whatever_its_label(line):
    from ledgerline.bank import mask_for_llm

    assert not ANY_LONG_NUMBER.search(mask_for_llm(line))


@pytest.mark.parametrize("line", MISLEADING)
def test_neither_the_primary_nor_the_escalation_model_sees_a_misleadingly_labelled_account(conn, ref, monkeypatch,
                                                                                           line):
    """The primary fails, so the document is also sent to the escalation model; both prompts are checked."""
    seen = []

    class Primary:
        model = "claude-haiku-5-5"

        def complete(self, system, prompt, max_tokens=2000):
            seen.append(prompt)
            return LLMResponse("not json", self.model, 1, 1, 1)

    class Escalation(Primary):
        model = "claude-opus-5-5"

    monkeypatch.setattr("ledgerline.extraction.get_client", Primary)
    monkeypatch.setattr("ledgerline.extraction.get_escalation_client", Escalation)
    process_document(conn, ref, DEV_001 + "\n" + line + "\n", "dev_001")
    assert len(seen) == 2
    assert_no_account_in(seen, DEV_001 + "\n" + line, "dev_001")


class TokenEcho:
    """A model that does what the prompt asks: copies masked tokens into the fields that contain them."""

    model = "fake"

    def __init__(self, invoice_number_line: str, answer: dict):
        self.line, self.answer = invoice_number_line, answer

    def complete(self, system, prompt, max_tokens=2000):
        [line] = [line for line in prompt.splitlines() if line.startswith(self.line)]
        value = line[len(self.line):].split("Dated")[0].strip(" :")  # the printed number, as the model sees it
        number = value
        return LLMResponse(json.dumps(dict(self.answer, invoice_number=number)), self.model, 1, 1, 1)


def test_an_all_digit_invoice_number_is_masked_in_the_prompt_and_restored_exactly(conn, ref, monkeypatch):
    raw = DEV_001.replace("SIS/26-27/0042", "202604250001")
    model = TokenEcho("Invoice No.", dict(LABELS["dev_001"]))
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: model)
    invoice = process_document(conn, ref, raw, "dev_001")
    assert invoice["invoice_number"] == "202604250001"
    assert invoice["review_reasons"] == []


def test_dev_014_invoice_number_round_trips_through_its_token(conn, ref, monkeypatch):
    raw = (REPO / "data" / "invoices" / "dev" / "dev_014.txt").read_text(encoding="utf-8")
    model = TokenEcho("Invoice number", dict(LABELS["dev_014"]))
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: model)
    invoice = process_document(conn, ref, raw, "dev_014")
    assert invoice["invoice_number"] == "CN-2026-04417"


def test_an_invoice_number_whose_token_was_not_copied_back_is_not_trusted(conn, ref, monkeypatch):
    raw = DEV_001.replace("SIS/26-27/0042", "202604250001")
    answering(monkeypatch, dict(LABELS["dev_001"], invoice_number="[N9:XXXXXXXX0001]"))  # a token that never existed
    invoice = process_document(conn, ref, raw, "dev_001")
    assert invoice["review_reasons"] == ["processing_error"]


@pytest.mark.parametrize("returned, expected", [("[N1:XXXXXXXX0001]", "202604250001"),   # token copied exactly
                                                ("XXXXXXXX0001", "202604250001"),        # bare mask, unique last 4
                                                ("[N9:XXXXXXXX0001]", "[N9:XXXXXXXX0001]")])  # never issued: kept
def test_restoring_tokens(returned, expected):
    from ledgerline.bank import restore_tokens, still_masked, tokenize_for_llm

    _, originals = tokenize_for_llm("Invoice No: 202604250001")
    assert restore_tokens(returned, originals) == expected
    assert still_masked(restore_tokens(returned, originals)) is (expected == returned)
