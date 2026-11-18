"""Realistic document text for tests that use a canned extraction.

Bank details are read from the document itself (never from the model), so a test whose model reports a bank account
must also print that account on the document, as real invoices do. The values are Sitara's from the starter's own
fake client and vendor master.
"""


def bank_lines(account: str | None = "50200012345678", ifsc: str | None = "ZEPH0001234") -> str:
    lines = ["Company's Bank Details", "  Bank Name : Zephyr Bank, Bhosari"]
    if account:
        lines.append(f"  A/c No.   : {account}")
    if ifsc:
        lines.append(f"  IFSC      : {ifsc}")
    return "\n".join(lines) + "\n"


def document(body: str = "TAX INVOICE", account: str | None = "50200012345678",
             ifsc: str | None = "ZEPH0001234") -> str:
    return f"{body}\nSitara Industrial Supplies Pvt. Ltd.\n{bank_lines(account, ifsc)}"


SITARA_DOCUMENT = document()
