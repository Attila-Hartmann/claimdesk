"""Deterministic checks on extracted fields. A model can misread a document; arithmetic and check digits cannot lie.

Each check returns issues as {"code", "field", "message"}. Codes are stable: the UI, the evals and the fraud model use them.
"""

import re
from datetime import date

PLATE = re.compile(r"^([A-Z]{4}-\d{3}|[A-Z]{3}-\d{3})$")
TAX = re.compile(r"^(\d{8})-([1-5])-(\d{2})$")
IBAN = re.compile(r"^HU\d{26}$")


def tax_number_valid(tax: str) -> bool:
    m = TAX.match(tax)
    if not m:
        return False
    core = m.group(1)
    s = sum(int(d) * w for d, w in zip(core[:7], (9, 7, 3, 1, 9, 7, 3), strict=True))
    return (10 - s % 10) % 10 == int(core[7])


def iban_valid(iban: str) -> bool:
    if not IBAN.match(iban):
        return False
    digits = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def _issue(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def check_document(doc_type: str, f: dict) -> list[dict]:
    out = []
    if doc_type == "claim_form":
        if not iban_valid(f.get("payout_iban", "")):
            out.append(_issue("iban_invalid", "payout_iban", "IBAN format or check digits are wrong"))
        if not PLATE.match(f.get("plate", "")):
            out.append(_issue("plate_format", "plate", "Not a Hungarian registration format"))
    elif doc_type == "repair_invoice":
        if not tax_number_valid(f.get("seller_tax_number", "")):
            out.append(_issue("tax_number_invalid", "seller_tax_number", "Tax number check digit does not match"))
        items = f.get("line_items") or []
        for i, li in enumerate(items):
            if li.get("quantity", 0) * li.get("unit_price_huf", 0) != li.get("net_huf"):
                out.append(_issue("line_math", f"line_items[{i}]", "quantity × unit price ≠ line net"))
        if sum(li.get("net_huf", 0) for li in items) != f.get("net_total_huf"):
            out.append(_issue("net_sum", "net_total_huf", "Line items do not add up to the net total"))
        if abs(round(f.get("net_total_huf", 0) * f.get("vat_rate", 0) / 100) - f.get("vat_huf", 0)) > 1:
            out.append(_issue("vat_math", "vat_huf", "VAT is not net × rate"))
        if f.get("net_total_huf", 0) + f.get("vat_huf", 0) != f.get("gross_total_huf"):
            out.append(_issue("gross_math", "gross_total_huf", "Net + VAT ≠ gross"))
        issue, fulfil = _date(f.get("issue_date", "")), _date(f.get("fulfilment_date", ""))
        if issue and fulfil and fulfil > issue:
            out.append(_issue("date_order", "fulfilment_date", "Fulfilment is after the invoice date"))
    return out


def check_claim(docs: dict[str, dict]) -> list[dict]:
    """Cross-document consistency for one claim. `docs` maps doc type → extracted fields."""
    out = []
    form, inv, eas = docs.get("claim_form"), docs.get("repair_invoice"), docs.get("accident_statement")
    if form and inv:
        if form.get("plate") != inv.get("plate"):
            out.append(_issue("plate_mismatch", "plate", "Invoice is for a different vehicle than the claim"))
        if (form.get("claimant_name") or "").casefold() != (inv.get("buyer_name") or "").casefold():
            out.append(_issue("buyer_mismatch", "buyer_name", "Invoice buyer is not the claimant"))
        loss, issued = _date(form.get("loss_datetime", "")), _date(inv.get("issue_date", ""))
        if loss and issued and issued < loss:
            out.append(_issue("invoice_before_loss", "issue_date", "Invoice is dated before the loss"))
        est = form.get("estimated_amount_huf") or 0
        if est and inv.get("gross_total_huf", 0) > 1.3 * est:
            out.append(_issue("invoice_over_estimate", "gross_total_huf", "Invoice exceeds the claimant's own estimate by more than 30%"))
    if form and eas and _date(form.get("loss_datetime", "")) != _date(eas.get("date", "")):
        out.append(_issue("date_mismatch", "date", "Accident statement date differs from the claim form"))
    return out
