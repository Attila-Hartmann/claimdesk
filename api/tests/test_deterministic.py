"""Everything that must not depend on a model: check digits, arithmetic rules, cross-document checks, scoring, data."""

import random

from claimdesk import extract, synth, validate


def test_generated_tax_numbers_and_ibans_pass_their_check_digits():
    rng = random.Random(1)
    assert all(validate.tax_number_valid(synth.tax_number(rng)) for _ in range(200))
    assert not any(validate.tax_number_valid(synth.tax_number(rng, valid=False)) for _ in range(200))
    assert all(validate.iban_valid(synth.iban(rng)) for _ in range(200))
    assert not validate.iban_valid("HU00" + "1" * 24)


def test_ground_truth_invoices_are_internally_consistent():
    claims = synth.generate(80)
    for c in claims:
        inv = next(d["fields"] for d in c.documents if d["type"] == "repair_invoice")
        codes = {i["code"] for i in validate.check_document("repair_invoice", inv)}
        assert codes <= {"tax_number_invalid"}, codes
        assert ("tax_number_invalid" in codes) == bool(c.signals["invalid_tax_number"])


def test_invoice_rules_catch_misread_numbers():
    inv = next(d["fields"] for d in synth.generate(1)[0].documents if d["type"] == "repair_invoice")
    misread = inv | {"vat_huf": inv["vat_huf"] + 900}  # OCR read 8 as 9 somewhere
    assert {"vat_math", "gross_math"} <= {i["code"] for i in validate.check_document("repair_invoice", misread)}


def test_cross_document_checks():
    form = {"plate": "AEBC-123", "claimant_name": "Kiss Anna", "loss_datetime": "2026-05-10T08:00", "estimated_amount_huf": 100_000}
    inv = {"plate": "AEBC-123", "buyer_name": "kiss anna", "issue_date": "2026-05-20", "gross_total_huf": 120_000}
    assert validate.check_claim({"claim_form": form, "repair_invoice": inv}) == []
    bad = inv | {"plate": "XYZ-999", "issue_date": "2026-05-01", "gross_total_huf": 200_000}
    codes = {i["code"] for i in validate.check_claim({"claim_form": form, "repair_invoice": bad})}
    assert codes == {"plate_mismatch", "invoice_before_loss", "invoice_over_estimate"}


def test_fraud_rate_is_realistic_and_signals_matter():
    claims = synth.generate(600)
    rate = sum(c.fraud for c in claims) / len(claims)
    assert 0.04 < rate < 0.15
    ring = [c for c in claims if c.signals["shop_in_ring"]]
    assert sum(c.fraud for c in ring) / len(ring) > 2 * rate


def test_scoring_is_per_field_and_whitespace_insensitive():
    truth = {"a": "Kovács  Anna", "b": 5, "items": [{"x": 1}, {"x": 2}], "tags": ["B: y", "A: x"]}
    assert all(extract.score(truth, {"a": "kovács anna", "b": 5, "items": [{"x": 1}, {"x": 2}], "tags": ["A: x", "B: y"]}).values())
    s = extract.score(truth, {"a": "Kovacs Anna", "b": 5, "items": [{"x": 1}]})
    assert s == {"a": False, "b": True, "items.count": False, "items.0.x": True, "items.1.x": False, "tags": False}
