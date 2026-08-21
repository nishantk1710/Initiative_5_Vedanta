"""Deterministic validation + the arithmetic-correction cases.

These are the tests that gate Phase 4's safe-correction protocol. Cases 14-16
from the spec are the important ones: today the validator blames `amount` for
every arithmetic mismatch, so a misread *quantity* gets "fixed" by corrupting
a correct amount. The xfail-marked test below encodes the intended behaviour
and is expected to fail until Phase 4 lands — that is the point of it.
"""

import pytest

from rules import (
    CONFIDENCE_ACCEPT_THRESHOLD,
    CONFIDENCE_REVIEW_THRESHOLD,
    evaluate_arithmetic,
    evaluate_field,
    parse_numeric,
)
from validator import run_validation


# --------------------------------------------------------------------------
# Field-level evaluation
# --------------------------------------------------------------------------

def test_extracted_field_above_accept_threshold_is_valid(field):
    status, rules = evaluate_field("description", field("Excavation", confidence=0.98))
    assert status == "valid"
    assert rules == []


def test_empty_optional_field_is_valid_not_ambiguous(field):
    """Regression: an absent optional column was previously judged by
    confidence_band(0.0) and came out 'ambiguous', which is what produced
    rows displaying 0% confidence."""
    status, rules = evaluate_field("unit", field("", confidence=0.0))
    assert status == "valid"
    assert rules == []


def test_empty_required_field_is_ambiguous(field):
    status, rules = evaluate_field("quantity", field("", confidence=0.0))
    assert status == "ambiguous"
    assert "required_field_missing" in rules


def test_low_confidence_extraction_is_ambiguous(field):
    status, rules = evaluate_field("rate", field("120", confidence=0.30))
    assert status == "ambiguous"
    assert "confidence_below_review_threshold" in rules


def test_mid_confidence_extraction_is_review(field):
    status, rules = evaluate_field("rate", field("120", confidence=0.70))
    assert status == "review"
    assert "confidence_below_accept_threshold" in rules


def test_non_numeric_value_in_numeric_field_flags_parse_failure(field):
    status, rules = evaluate_field("quantity", field("12S0", confidence=0.95))
    assert status == "ambiguous"
    assert "numeric_parse_failure" in rules


def test_confidence_bands_are_ordered():
    assert 0 < CONFIDENCE_REVIEW_THRESHOLD < CONFIDENCE_ACCEPT_THRESHOLD <= 1.0


@pytest.mark.parametrize(
    "raw,expected",
    [("1,250", 1250.0), ("$99.50", 99.5), ("  12 ", 12.0), ("12S0", None), ("", None), (None, None)],
)
def test_parse_numeric(raw, expected):
    assert parse_numeric(raw) == expected


# --------------------------------------------------------------------------
# Arithmetic: amount ~ quantity * rate
# --------------------------------------------------------------------------

def test_correct_arithmetic_passes(row):
    """Spec case 16: correct arithmetic must NOT be flagged or changed."""
    r = row(description="Excavation", quantity="500", rate="1250", amount="625000")
    assert evaluate_arithmetic(r) == ("valid", [], None)


def test_arithmetic_mismatch_is_detected(row):
    r = row(description="Excavation", quantity="500", rate="1250", amount="999")
    status, rules, suspect = evaluate_arithmetic(r)
    assert status == "ambiguous"
    assert "arithmetic_mismatch" in rules
    assert suspect in ("quantity", "rate", "amount")


def test_arithmetic_absent_when_quantity_or_rate_missing(row):
    """A row with no unit rate (common on POS receipts) has no arithmetic to
    check — that is not the same thing as a failed check."""
    r = row(description="Shoes", amount="699")
    assert evaluate_arithmetic(r) is None


def test_tax_inclusive_amount_is_accepted(row):
    """quantity*rate + taxAmount ~ amount — not every invoice line is pre-tax."""
    r = row(description="Shoes", quantity="1", rate="600", amount="699", taxAmount="99")
    assert evaluate_arithmetic(r) == ("valid", [], None)


def test_arithmetic_tolerates_small_rounding(row):
    r = row(description="Widget", quantity="3", rate="33.33", amount="100")
    assert evaluate_arithmetic(r) == ("valid", [], None)


def test_mismatch_suspects_the_lowest_confidence_field(row):
    """The deterministic first-pass guess: among quantity/rate/amount, blame
    whichever one the OCR engine itself was least sure about."""
    r = row(
        description="Drainage works",
        quantity={"value": "11", "source": "paddleocr", "confidence": 0.62, "page": 1, "bbox": [0, 0, 1, 1]},
        rate={"value": "18000", "source": "paddleocr", "confidence": 0.99, "page": 1, "bbox": [0, 0, 1, 1]},
        amount={"value": "19800", "source": "paddleocr", "confidence": 0.99, "page": 1, "bbox": [0, 0, 1, 1]},
    )
    _, _, suspect = evaluate_arithmetic(r)
    assert suspect == "quantity"


# --------------------------------------------------------------------------
# Row-level validation
# --------------------------------------------------------------------------

def test_clean_row_is_valid(row):
    rows = run_validation([row(description="Excavation", quantity="500", rate="1250", amount="625000")])
    assert rows[0]["status"] == "valid"


def test_arithmetic_mismatch_makes_row_ambiguous(row):
    """All three correlated fields share the fixture's default confidence
    (0.97), so the tie-break is arbitrary among them — assert the row-level
    outcome and that SOME field carries the rule, not which one specifically
    (that specific-field behavior is covered by
    test_mismatch_suspects_the_lowest_confidence_field above, using distinct
    confidences so the answer isn't a coin flip)."""
    rows = run_validation([row(description="Excavation", quantity="500", rate="1250", amount="999")])
    assert rows[0]["status"] == "ambiguous"
    assert any(t.endswith(":arithmetic_mismatch") for t in rows[0]["rules_triggered"])


def test_llm_extracted_row_is_floored_to_review(row):
    """An LLM-derived row must never read as 'valid' — it bypassed geometry."""
    r = row(description="Shoes", quantity="1", rate="699", amount="699")
    for f in r.values():
        f["source"] = "llm"
        f["confidence"] = 0.95  # high enough that bands alone would say 'valid'
    r["_llm_extracted"] = True
    rows = run_validation([r])
    assert rows[0]["status"] == "review"
    assert "llm_extracted_structure" in rows[0]["rules_triggered"]


def test_incomplete_override_short_circuits_field_evaluation(row):
    r = row(description="some unparsed table line", quantity="", rate="", amount="")
    r["_status_override"] = "incomplete"
    rows = run_validation([r])
    assert rows[0]["status"] == "incomplete"
    assert rows[0]["rules_triggered"] == ["table_header_not_identified"]


def test_internal_markers_never_leak_into_output(row):
    """_position_guessed / _llm_extracted are routing internals, not result data."""
    r = row(description="X", quantity="1", rate="1", amount="1")
    r["_position_guessed"] = True
    r["_llm_extracted"] = True
    rows = run_validation([r])
    assert "_position_guessed" not in rows[0]
    assert "_llm_extracted" not in rows[0]
    assert "_status_override" not in rows[0]


def test_optional_fields_stay_absent_not_null(row):
    """Spec: omit inapplicable fields rather than emitting null columns."""
    rows = run_validation([row(description="Shoes", quantity="1", rate="699", amount="699")])
    for key in ("unit", "itemCode", "taxRate", "taxAmount"):
        assert key not in rows[0]


# --------------------------------------------------------------------------
# Spec cases 14 & 15: WHICH field is wrong?
# --------------------------------------------------------------------------

def test_mismatch_attribution_when_amount_is_the_wrong_field(row):
    """Spec case 15. qty=500, rate=1250 (both high confidence), amount misread.
    Blaming `amount` here is correct."""
    r = row(
        description="Excavation",
        quantity={"value": "500", "source": "paddleocr", "confidence": 0.99, "page": 1, "bbox": [0, 0, 1, 1]},
        rate={"value": "1250", "source": "paddleocr", "confidence": 0.99, "page": 1, "bbox": [0, 0, 1, 1]},
        amount={"value": "62500", "source": "paddleocr", "confidence": 0.55, "page": 1, "bbox": [0, 0, 1, 1]},
    )
    rows = run_validation([r])
    assert rows[0]["status"] == "ambiguous"
    assert "amount:arithmetic_mismatch" in rows[0]["rules_triggered"]


def test_mismatch_is_not_blindly_attributed_to_amount(row):
    """Spec case 14. The real defect: qty was misread (1.1 -> 11) while rate and
    amount are both correct at 0.99 confidence. `amount` is the *most* trustworthy
    field in the row, so pinning arithmetic_mismatch on it is precisely wrong —
    that attribution is what tells llm.py to rewrite it.

    Asserts on the arithmetic attribution specifically. A generic
    "quantity is mentioned somewhere" check would pass for the wrong reason,
    since the low-confidence quantity already draws its own separate
    confidence_below_accept_threshold flag.
    """
    r = row(
        description="Drainage works",
        quantity={"value": "11", "source": "paddleocr", "confidence": 0.62, "page": 1, "bbox": [0, 0, 1, 1]},
        rate={"value": "18000", "source": "paddleocr", "confidence": 0.99, "page": 1, "bbox": [0, 0, 1, 1]},
        amount={"value": "19800", "source": "paddleocr", "confidence": 0.99, "page": 1, "bbox": [0, 0, 1, 1]},
    )
    rows = run_validation([r])
    triggered = rows[0]["rules_triggered"]

    assert "amount:arithmetic_mismatch" not in triggered, (
        "arithmetic_mismatch was pinned on `amount`, the highest-confidence field in "
        f"the row — this is the attribution that causes the corruption. Got {triggered}"
    )
    assert any("arithmetic_mismatch" in t for t in triggered), (
        f"the mismatch itself must still be reported, just not against amount. Got {triggered}"
    )
