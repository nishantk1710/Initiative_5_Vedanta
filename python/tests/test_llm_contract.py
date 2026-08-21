"""LLM boundary contract.

These test OUR handling of model output, not the model's judgement — a stub
stands in for the transport so they run fast and offline. What matters here is
the no-hallucination and provenance guarantees: whatever the model returns,
the pipeline must never emit a fabricated or unattributed value.
"""

import pytest

import llm_line_items
from llm_line_items import LLM_FIELD_CONFIDENCE, extract_line_items_via_llm


@pytest.fixture
def stub_model(monkeypatch):
    """Replace the transport so a canned response can be injected."""

    def _set(response):
        monkeypatch.setattr(llm_line_items, "post_chat_json", lambda *a, **k: response)

    return _set


def _ocr(text, x0, y0, x1, y1, page=1):
    return {
        "value": text,
        "source": "paddleocr",
        "confidence": 0.97,
        "page": page,
        "bbox": [float(x0), float(y0), float(x1), float(y1)],
    }


PAGE_BBOX = [0.0, 0.0, 800.0, 1200.0]


# --------------------------------------------------------------------------
# Failure modes must degrade, never crash or invent
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "response",
    [
        None,                                   # transport failed / unconfigured
        {},                                     # no lineItems key
        {"lineItems": None},                    # wrong type
        {"lineItems": "not a list"},
        {"wrong_key": []},
        [],                                     # top-level array instead of object
        "a bare string",
    ],
)
def test_malformed_response_yields_no_rows(stub_model, response):
    stub_model(response)
    assert extract_line_items_via_llm(["Bread  2  60"], 1, PAGE_BBOX) == []


def test_empty_line_items_is_respected(stub_model):
    """The model correctly reporting 'nothing here' must not be overridden."""
    stub_model({"lineItems": []})
    assert extract_line_items_via_llm(["Some prose with no items."], 1, PAGE_BBOX) == []


def test_no_text_lines_short_circuits_without_calling_model(monkeypatch):
    called = []
    monkeypatch.setattr(llm_line_items, "post_chat_json", lambda *a, **k: called.append(1))
    assert extract_line_items_via_llm(["", "   "], 1, PAGE_BBOX) == []
    assert called == [], "must not spend a model call on empty input"


# --------------------------------------------------------------------------
# No-hallucination policy (spec criterion 11)
# --------------------------------------------------------------------------

def test_item_missing_required_description_is_dropped(stub_model):
    stub_model({"lineItems": [{"amount": 60}]})
    assert extract_line_items_via_llm(["Bread 60"], 1, PAGE_BBOX) == []


def test_item_missing_required_amount_is_dropped(stub_model):
    stub_model({"lineItems": [{"description": "Bread"}]})
    assert extract_line_items_via_llm(["Bread"], 1, PAGE_BBOX) == []


def test_blank_description_is_dropped(stub_model):
    stub_model({"lineItems": [{"description": "   ", "amount": 60}]})
    assert extract_line_items_via_llm(["Bread 60"], 1, PAGE_BBOX) == []


def test_non_object_items_are_skipped(stub_model):
    stub_model({"lineItems": ["Bread", 42, None, {"description": "Milk", "amount": 55}]})
    rows = extract_line_items_via_llm(["Milk 55"], 1, PAGE_BBOX)
    assert len(rows) == 1
    assert rows[0]["description"]["value"] == "Milk"


def test_null_and_empty_optional_fields_are_omitted_not_stored(stub_model):
    """Spec: omit absent fields rather than emitting nulls."""
    stub_model({"lineItems": [{
        "description": "Bread", "amount": 60,
        "unit": None, "rate": None, "itemCode": "", "taxAmount": None,
    }]})
    row = extract_line_items_via_llm(["Bread 60"], 1, PAGE_BBOX)[0]
    for key in ("unit", "rate", "itemCode", "taxAmount"):
        assert key not in row, f"{key} should be absent, not null"


# --------------------------------------------------------------------------
# Provenance & status (spec criteria 10, 14, 22)
# --------------------------------------------------------------------------

def test_all_fields_tagged_llm_source_and_fixed_confidence(stub_model):
    stub_model({"lineItems": [{"description": "Bread", "amount": 60, "quantity": 2}]})
    row = extract_line_items_via_llm(["Bread  2  60"], 1, PAGE_BBOX)[0]
    for key in ("description", "amount", "quantity"):
        assert row[key]["source"] == "llm"
        assert row[key]["confidence"] == LLM_FIELD_CONFIDENCE


def test_rows_marked_for_review_flooring(stub_model):
    """The marker validator.py consumes to floor the row to 'review'."""
    stub_model({"lineItems": [{"description": "Bread", "amount": 60}]})
    row = extract_line_items_via_llm(["Bread 60"], 1, PAGE_BBOX)[0]
    assert row["_llm_extracted"] is True


def test_confidence_sits_in_the_review_band():
    """0.65 must land in review (0.60-0.84) — below 0.60 would loop it back
    into the ambiguous-field normalizer."""
    from rules import CONFIDENCE_ACCEPT_THRESHOLD, CONFIDENCE_REVIEW_THRESHOLD

    assert CONFIDENCE_REVIEW_THRESHOLD <= LLM_FIELD_CONFIDENCE < CONFIDENCE_ACCEPT_THRESHOLD


def test_bbox_recovered_from_matching_ocr_box(stub_model):
    """Provenance: a returned value that matches an OCR token should point at
    that token's real position, not the whole page."""
    stub_model({"lineItems": [{"description": "Bread", "amount": 60}]})
    ocr = [_ocr("Bread", 30, 400, 200, 430), _ocr("60", 600, 400, 660, 430)]
    row = extract_line_items_via_llm(["Bread  60"], 1, PAGE_BBOX, ocr_values=ocr)[0]
    assert row["description"]["bbox"] == [30.0, 400.0, 200.0, 430.0]


def test_bbox_falls_back_to_page_when_no_match(stub_model):
    """An honest approximate box beats a confidently wrong one."""
    stub_model({"lineItems": [{"description": "Nonexistent item", "amount": 60}]})
    row = extract_line_items_via_llm(["Bread 60"], 1, PAGE_BBOX, ocr_values=[_ocr("Bread", 30, 400, 200, 430)])[0]
    assert row["description"]["bbox"] == PAGE_BBOX


def test_distant_substring_match_is_rejected(stub_model):
    """A generic short value must not match some unrelated token far away on
    the page — that produced amounts pointing at the wrong section."""
    stub_model({"lineItems": [{"description": "Bread", "amount": 1}]})
    ocr = [
        _ocr("Bread", 30, 400, 200, 430),
        _ocr("1", 700, 5, 720, 25),        # a stray '1' far above (page number)
    ]
    row = extract_line_items_via_llm(["Bread"], 1, PAGE_BBOX, ocr_values=ocr)[0]
    assert row["amount"]["bbox"] != [700.0, 5.0, 720.0, 25.0]


# --------------------------------------------------------------------------
# Value coercion
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [(60, 60.0), (60.5, 60.5), ("60", 60.0), ("1,250", 1250.0)])
def test_numeric_values_coerced(stub_model, raw, expected):
    stub_model({"lineItems": [{"description": "X", "amount": raw}]})
    row = extract_line_items_via_llm(["X"], 1, PAGE_BBOX)[0]
    assert row["amount"]["value"] == expected


def test_unparseable_numeric_kept_as_string_for_validation(stub_model):
    stub_model({"lineItems": [{"description": "X", "amount": 1, "quantity": "abc"}]})
    row = extract_line_items_via_llm(["X"], 1, PAGE_BBOX)[0]
    assert row["quantity"]["value"] == "abc"


def test_prompt_contains_no_format_specific_terms():
    """The fallback must stay format-agnostic — no vendor/country/tax terms."""
    prompt = llm_line_items._SYSTEM_PROMPT.lower()
    for banned in ("walkway", "gst", "hsn", "cgst", "sgst", "igst", "rupee", "india", "footwear"):
        assert banned not in prompt, f"format-specific term {banned!r} leaked into the prompt"
