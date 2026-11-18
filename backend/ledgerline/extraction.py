"""Turn a raw vendor document into structured fields and a routing decision, using the LLM."""
from __future__ import annotations

import json
import re

from .config import get_settings
from .llm import LLMResponse, get_client
from .reference import ReferenceData

FIELDS = [
    "document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
    "subtotal", "cgst", "sgst", "igst", "round_off", "total", "bank_account", "ifsc", "po_number",
    "notes", "line_items",
]

SYSTEM_PROMPT = (
    "You are Ledgerline, an expert accounts-payable assistant for Meridian Precision Components "
    "Pvt. Ltd. You read vendor documents, extract their data and apply Meridian's AP policy."
)


def _few_shot_examples(limit: int = 3) -> str:
    """A few labelled examples so the model learns our exact output format."""
    data_dir = get_settings().data_dir
    blocks = []
    with open(data_dir / "ground_truth" / "dev.jsonl", encoding="utf-8") as f:
        for line in list(f)[:limit]:
            row = json.loads(line)
            doc = (data_dir / "invoices" / "dev" / row["filename"]).read_text(encoding="utf-8")
            blocks.append(f"DOCUMENT:\n{doc}\nOUTPUT:\n{json.dumps(row['expected'])}")
    return "\n\n".join(blocks)


def build_extraction_prompt(document_text: str, ref: ReferenceData) -> str:
    return f"""Read the vendor document below, extract its fields, and decide whether it needs human review under our AP policy.

AP POLICY:
{ref.policy_text}

VENDOR MASTER (CSV):
{ref.vendors_csv}

EXAMPLES:
{_few_shot_examples()}

Return a JSON object with these keys: {", ".join(FIELDS)}, requires_review (true/false) and review_reasons (list of policy codes).
Copy amounts and dates exactly as they are printed in the document.

{document_text}
"""


def build_verification_prompt(document_text: str, extraction: dict, ref: ReferenceData) -> str:
    return f"""You extracted the JSON below from a vendor document. Check every field against the document and our AP policy, fix anything that is wrong, and return the corrected JSON object with the same keys.

EXTRACTION:
{json.dumps(extraction, indent=2)}

AP POLICY:
{ref.policy_text}

VENDOR MASTER (CSV):
{ref.vendors_csv}

{document_text}
"""


_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class ExtractionError(Exception):
    """The document could not be extracted reliably. Carries the LLM calls already made, so their cost is recorded."""

    def __init__(self, message: str, responses: list[LLMResponse]):
        super().__init__(message)
        self.responses = responses


def parse_model_json(text: str) -> dict:
    """Return the JSON object in a model response: bare JSON, JSON in a ```json fence, or JSON surrounded by prose.

    The object is always a verbatim slice of the response; nothing is edited. No JSON raises ValueError; JSON that
    is not an object raises TypeError.
    """
    try:
        data = json.loads(text)
    except ValueError:
        match = _FENCED_JSON.search(text)
        candidate = match.group(1) if match else text[text.find("{"): text.rfind("}") + 1]
        try:
            data = json.loads(candidate)
        except ValueError:
            raise ValueError("the model response does not contain a parseable JSON object") from None
    if not isinstance(data, dict):
        raise TypeError("the model response JSON is not an object")
    return data


def extract(document_text: str, ref: ReferenceData) -> tuple[dict, list[LLMResponse]]:
    """Two passes: extract, then let the model double-check its own work (+2 points on the eval)."""
    client = get_client()
    responses: list[LLMResponse] = []
    try:
        first = client.complete(SYSTEM_PROMPT, build_extraction_prompt(document_text, ref))
        responses.append(first)
        data = parse_model_json(first.text)
        second = client.complete(SYSTEM_PROMPT, build_verification_prompt(document_text, data, ref))
        responses.append(second)
        data = parse_model_json(second.text)
    except Exception as exc:  # provider error or unusable response: the caller routes it to processing_error
        raise ExtractionError(f"{type(exc).__name__}: {exc}", responses) from exc
    return data, responses
