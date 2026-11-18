"""Bank details, read locally and deterministically; never from the LLM (AP_POLICY section 5).

The model only ever sees masked account numbers, so `bank_details_changed` is decided from the account numbers
and IFSC codes this module reads from the original document. Anything ambiguous or unverifiable goes to review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIGITS = r"\d(?:[ \-]?\d){7,23}"  # 8-24 digits, optionally grouped by single spaces or hyphens

# Labelled account numbers, as printed in the formats Meridian receives:
#   "A/c No.   : 50200012345678"   "A/c No: 50200012345678"   "... Vapi A/c 31840100022917, IFSC ..."
#   "Account No: ..."  "Acct # ..."  and e-invoice JSON  "AccDet": "50200098765432"
_LABELLED_ACCOUNT = [
    re.compile(r"(?i)(?<![A-Za-z])(?:a/c|acct|account)(?:\s*(?:no\.?|number|#))?\s*[:\-]?\s*(" + _DIGITS + r")(?!\d)"),
    re.compile(r'"(?:AccDet|PayeeAcctNr|AcctNo|AccountNo|BankAcctNo)"\s*:\s*"?(' + _DIGITS + r")(?!\d)"),
]
_IFSC = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{4}0[A-Za-z0-9]{6})(?![A-Za-z0-9])")

# What may leave Ledgerline: EVERY run of 9 or more digits (optionally grouped by single spaces or hyphens) is
# masked, wherever it appears and whatever its label says, because a label cannot be trusted ("Invoice Ref:
# 50200012345678" may well be an account). Each is replaced by a numbered token that keeps only the last four digits,
# e.g. [N1:XXXXXXXXXX5678]. The model copies tokens into its answer; Ledgerline restores the originals locally, so an
# all-digit invoice or PO number still comes back exactly.
_LONG_NUMBER = re.compile(r"(?<!\d)\d(?:[ \-]?\d){8,}(?!\d)")
_TOKEN = re.compile(r"\[N(\d+):X*(\d{4})\]")
_BARE_MASK = re.compile(r"X{3,}(\d{4})")


@dataclass
class BankDetails:
    accounts: list[str] = field(default_factory=list)  # distinct, digits only, in order of appearance
    ifscs: list[str] = field(default_factory=list)     # distinct, upper case

    @property
    def account(self) -> str | None:
        return self.accounts[0] if len(self.accounts) == 1 else None

    @property
    def ifsc(self) -> str | None:
        return self.ifscs[0] if len(self.ifscs) == 1 else None


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def find_bank_details(raw_text: str) -> BankDetails:
    found = BankDetails()
    for pattern in _LABELLED_ACCOUNT:
        for match in pattern.finditer(raw_text or ""):
            number = digits(match.group(1))
            if len(number) >= 9 and number not in found.accounts:
                found.accounts.append(number)
    for match in _IFSC.finditer(raw_text or ""):
        code = match.group(1).upper()
        if code not in found.ifscs:
            found.ifscs.append(code)
    return found


def _mask(number: str) -> str:
    plain = digits(number)
    return "X" * (len(plain) - 4) + plain[-4:]


def tokenize_for_llm(raw_text: str) -> tuple[str, dict[str, str]]:
    """The document as it may be sent to an external LLM (AP_POLICY 5.1), and the local map token -> original text."""
    originals: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        original = match.group(0)
        for token, seen in originals.items():
            if seen == original:
                return token
        token = f"[N{len(originals) + 1}:{_mask(original)}]"
        originals[token] = original
        return token

    return _LONG_NUMBER.sub(replace, raw_text or ""), originals


def mask_for_llm(raw_text: str) -> str:
    return tokenize_for_llm(raw_text)[0]


def restore_tokens(value, originals: dict[str, str]):
    """Put the original numbers back into the model's answer (strings, lists and dicts, recursively). A token the model
    copied exactly is restored; a bare 'XXXX1234' is restored only when exactly one masked number ends in 1234.
    Anything else is left masked, so callers can see that the value could not be recovered."""
    if isinstance(value, dict):
        return {k: restore_tokens(v, originals) for k, v in value.items()}
    if isinstance(value, list):
        return [restore_tokens(v, originals) for v in value]
    if not isinstance(value, str):
        return value
    restored = _TOKEN.sub(lambda m: originals.get(m.group(0), m.group(0)), value)
    if _TOKEN.search(restored):  # a token we never issued: leave it alone so it is seen as unresolved
        return restored

    def bare(match: re.Match) -> str:
        candidates = [o for t, o in originals.items() if t.endswith(f"{match.group(1)}]")]
        return candidates[0] if len(candidates) == 1 else match.group(0)

    return _BARE_MASK.sub(bare, restored)


def still_masked(value) -> bool:
    return isinstance(value, str) and bool(_TOKEN.search(value) or _BARE_MASK.search(value))
