"""Safe correction protocol (Phase 4).

The critical property under test: a field the OCR engine was already
confident about must NEVER be overwritten, no matter what any proposal says
— that is the deterministic gate, not a prompt instruction, so it holds even
if the model itself gets it wrong.
"""

import pytest

import correction
import llm
from validator import run_validation


@pytest.fixture(autouse=True)
def _no_ambient_azure_calls(monkeypatch):
    """normalize_ambiguous()'s per-field fallback path (llm.py's
    _call_azure_foundry) is a SEPARATE call from correction.py's
    propose_correction() — this suite is only about the latter, so the
    former must never contribute here regardless of whether some other
    test in this session happened to import main.py (which loads real
    Azure credentials into os.environ via load_dotenv at module level).
    Without this, these tests' pass/fail would depend on test run order
    and on ambient .env state, neither of which they should."""
    monkeypatch.setattr(llm, "post_chat_json", lambda *a, **k: None)


@pytest.fixture
def stub_model(monkeypatch):
    def _set(response):
        monkeypatch.setattr(correction, "post_chat_json", lambda *a, **k: response)

    return _set


def _f(value, confidence, source="paddleocr"):
    return {"value": value, "source": source, "confidence": confidence, "page": 1, "bbox": [0, 0, 1, 1]}


def _row(**fields):
    return dict(fields)


# --------------------------------------------------------------------------
# propose_correction: malformed / declined responses
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"suspected_field": None, "action": "no_safe_correction"},
        {"suspected_field": "amount"},  # missing proposed_value
        {"suspected_field": "not_a_real_field", "proposed_value": "5"},
        {"suspected_field": "description", "proposed_value": "5"},  # not a correlated numeric field
        "a bare string",
        [],
    ],
)
def test_propose_correction_returns_none_on_malformed_or_declined(stub_model, response):
    stub_model(response)
    row = _row(quantity=_f("11", 0.62), rate=_f("18000", 0.99), amount=_f("19800", 0.99))
    assert correction.propose_correction(row) is None


# --------------------------------------------------------------------------
# apply_if_safe: the acceptance gate
# --------------------------------------------------------------------------

def test_high_confidence_field_is_never_overwritten():
    """The core guarantee. Even a well-formed, plausible-looking proposal
    targeting a field the engine already trusted must be rejected."""
    row = _row(quantity=_f("11", 0.62), rate=_f("18000", 0.99), amount=_f("19800", 0.99))
    proposal = {
        "suspected_field": "amount", "original_value": "19800",
        "proposed_value": "198000", "reason": "matches quantity * rate", "confidence": 0.95,
    }
    applied = correction.apply_if_safe(row, proposal)
    assert applied is False
    assert row["amount"]["value"] == "19800", "amount must be untouched — this is the corruption bug"
    assert row["amount"]["confidence"] == 0.99


def test_low_confidence_field_can_be_corrected_when_it_resolves_the_mismatch():
    row = _row(quantity=_f("11", 0.62), rate=_f("18000", 0.99), amount=_f("19800", 0.99))
    proposal = {
        "suspected_field": "quantity", "original_value": "11",
        "proposed_value": "1.1", "reason": "decimal point dropped by OCR", "confidence": 0.9,
    }
    applied = correction.apply_if_safe(row, proposal)
    assert applied is True
    assert row["quantity"]["value"] == 1.1
    assert row["quantity"]["source"] == "llm"
    assert row["quantity"]["status"] == "review"
    assert "llm_corrected" in row["quantity"]["rules_triggered"]


def test_correction_confidence_is_capped_below_accept_threshold():
    """A correction must never claim more trust than a direct high-confidence
    read would — it's still an inference, not an observation."""
    from rules import CONFIDENCE_ACCEPT_THRESHOLD

    row = _row(quantity=_f("11", 0.62), rate=_f("18000", 0.99), amount=_f("19800", 0.99))
    proposal = {"suspected_field": "quantity", "proposed_value": "1.1", "confidence": 0.999}
    correction.apply_if_safe(row, proposal)
    assert row["quantity"]["confidence"] < CONFIDENCE_ACCEPT_THRESHOLD


def test_correction_rejected_when_it_does_not_actually_fix_the_arithmetic():
    """A proposal that doesn't resolve the mismatch isn't worth the mutation
    risk, even if the target field is low-confidence."""
    row = _row(quantity=_f("11", 0.62), rate=_f("18000", 0.99), amount=_f("19800", 0.99))
    proposal = {"suspected_field": "quantity", "proposed_value": "7", "confidence": 0.9}  # doesn't fix it
    applied = correction.apply_if_safe(row, proposal)
    assert applied is False
    assert row["quantity"]["value"] == "11"


def test_non_numeric_proposal_is_rejected():
    row = _row(quantity=_f("11", 0.62), rate=_f("18000", 0.99), amount=_f("19800", 0.99))
    proposal = {"suspected_field": "quantity", "proposed_value": "not a number", "confidence": 0.9}
    assert correction.apply_if_safe(row, proposal) is False


def test_boundary_confidence_at_accept_threshold_is_rejected():
    """>= accept threshold is the documented cutoff, not > — a field sitting
    exactly at the boundary is still "already trusted"."""
    from rules import CONFIDENCE_ACCEPT_THRESHOLD

    row = _row(
        quantity=_f("11", CONFIDENCE_ACCEPT_THRESHOLD), rate=_f("18000", 0.99), amount=_f("19800", 0.99)
    )
    proposal = {"suspected_field": "quantity", "proposed_value": "1.1", "confidence": 0.9}
    assert correction.apply_if_safe(row, proposal) is False


# --------------------------------------------------------------------------
# Full integration: the exact reproduced corruption scenario, end to end
# --------------------------------------------------------------------------

def test_end_to_end_reproduction_amount_is_never_corrupted(monkeypatch):
    """Reproduces the live bug exactly: qty 1.1 misread as 11, rate and
    amount both correct at 0.99 confidence. A model that (correctly or not)
    is asked to propose against 'amount' must be blocked by the gate; a
    model proposing the real fix against 'quantity' must succeed. Either
    way, amount must survive unchanged and the row must never read 'valid'.
    """

    def fake_model(*a, **k):
        return {
            "suspected_field": "quantity",
            "original_value": "11",
            "proposed_value": "1.1",
            "reason": "OCR likely dropped a decimal point",
            "confidence": 0.9,
        }

    monkeypatch.setattr(correction, "post_chat_json", fake_model)

    row = {
        "description": _f("Drainage works", 0.99, source="pymupdf"),
        "quantity": _f("11", 0.62),
        "unit": _f("km", 0.99),
        "rate": _f("18000", 0.99),
        "amount": _f("19800", 0.99),
    }

    validated = run_validation([row])
    assert validated[0]["status"] == "ambiguous"
    # confirm attribution landed on quantity, not amount (Phase 4's first fix)
    assert "quantity:arithmetic_mismatch" in validated[0]["rules_triggered"]
    assert "amount:arithmetic_mismatch" not in validated[0]["rules_triggered"]

    final_rows, corrected_count = llm.normalize_ambiguous(validated)
    final = final_rows[0]

    assert final["amount"]["value"] == "19800", "amount must never change — this is the exact corruption case"
    assert final["amount"]["confidence"] == 0.99
    assert final["quantity"]["value"] == 1.1
    assert final["status"] in ("review",), "a corrected row must surface for human confirmation, never silently valid"
    assert corrected_count == 1


def test_end_to_end_declines_when_model_returns_no_safe_correction(monkeypatch):
    """If the model can't confidently identify the issue, the row stays
    ambiguous rather than something being forced through."""
    monkeypatch.setattr(
        correction, "post_chat_json", lambda *a, **k: {"suspected_field": None, "action": "no_safe_correction"}
    )
    row = {
        "description": _f("Drainage works", 0.99, source="pymupdf"),
        "quantity": _f("11", 0.62),
        "unit": _f("km", 0.99),
        "rate": _f("18000", 0.99),
        "amount": _f("19800", 0.99),
    }
    validated = run_validation([row])
    final_rows, corrected_count = llm.normalize_ambiguous(validated)
    assert corrected_count == 0
    assert final_rows[0]["quantity"]["value"] == "11"
    assert final_rows[0]["status"] == "ambiguous"


def test_end_to_end_model_wrongly_targets_amount_is_still_blocked(monkeypatch):
    """Even if the model's own reasoning is wrong and it suspects the
    high-confidence field, the deterministic gate — not the prompt — is
    what actually prevents the corruption."""
    monkeypatch.setattr(
        correction,
        "post_chat_json",
        lambda *a, **k: {
            "suspected_field": "amount",
            "proposed_value": "198000",
            "reason": "matches quantity * rate",
            "confidence": 0.95,
        },
    )
    row = {
        "description": _f("Drainage works", 0.99, source="pymupdf"),
        "quantity": _f("11", 0.62),
        "unit": _f("km", 0.99),
        "rate": _f("18000", 0.99),
        "amount": _f("19800", 0.99),
    }
    validated = run_validation([row])
    final_rows, corrected_count = llm.normalize_ambiguous(validated)
    assert corrected_count == 0
    assert final_rows[0]["amount"]["value"] == "19800"
    assert final_rows[0]["status"] == "ambiguous"
