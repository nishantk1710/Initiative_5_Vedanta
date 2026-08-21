"""Router heuristics, region selection, and the disjoint-roles invariant.

These are pure-logic tests — no OCR, no model loading — so they stay fast.
"""

import pytest

from router import is_meaningful_text
from layout import select_regions, classify_region_label
from metadata_extractor import is_metadata_line, is_line_item_text
from classifier import classify_document


# --------------------------------------------------------------------------
# Router: meaningful-text heuristics (spec case 13)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n  \t ",
        "7",                                        # page number only
        "." * 60,                                   # dot leaders
        "_" * 40,                                   # form underscores
        "-" * 25 + " " + "-" * 25,                  # rule line
        "12 34 56 78 90 12 34 56 78 90 12 34 56",   # digits, no words
        "ab cd ef gh ij kl mn op qr st uv wx yz",    # no 3+ letter words
    ],
)
def test_junk_text_layers_are_not_meaningful(text):
    """A scanned page often carries a junk text layer. Treating it as
    'digital' would skip OCR entirely and silently lose the whole page."""
    assert is_meaningful_text(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "SCOPE OF WORK - MINING PROJECT ALPHA. Contractor shall clear the site.",
        "This agreement is made between Alpha Limited and Beta Incorporated today.",
        "Description Quantity Unit Rate Amount Site clearing twelve hectares total",
    ],
)
def test_real_body_text_is_meaningful(text):
    assert is_meaningful_text(text) is True


def test_meaningful_text_requires_minimum_length():
    assert is_meaningful_text("Short real words here") is False  # < 40 chars


# --------------------------------------------------------------------------
# Region selection: physical type -> keep/drop + routing
# --------------------------------------------------------------------------

def _region(rtype, content="", bbox=(0, 0, 10, 10)):
    return {"type": rtype, "bbox": list(bbox), "content": content}


def test_table_region_is_kept_as_line_item():
    kept = select_regions([_region("table", "Description Qty Rate Amount")])
    assert len(kept) == 1
    assert kept[0]["category"] == "table"
    assert kept[0]["role"] == "line_item"


def test_handwriting_region_is_kept_as_line_item():
    kept = select_regions([_region("handwriting", "12S0")])
    assert kept[0]["role"] == "line_item"


def test_logo_and_seal_regions_are_dropped(  ):
    """Spec case 22: a logo/seal carries no text data and must never become
    extracted content."""
    kept = select_regions([_region("image"), _region("logo"), _region("seal"), _region("chart")])
    assert kept == []


def test_header_region_is_kept_but_routed_to_metadata():
    """Headers are OCR'd (the classifier needs to see 'TAX INVOICE') but must
    never reach line-item extraction."""
    kept = select_regions([_region("header", "TAX INVOICE")])
    assert len(kept) == 1
    assert kept[0]["role"] == "metadata"


def test_gst_line_with_digits_routes_to_metadata_not_line_item():
    """Spec case 21. Digit-presence alone must not qualify text as a line
    item, or every GST/bill-number line becomes a fake row."""
    kept = select_regions([_region("text", "GST NO. 27AAACM4754E1ZL")])
    assert kept[0]["role"] == "metadata"


def test_tabular_looking_text_routes_to_line_item():
    kept = select_regions([_region("text", "Site clearing 12.5 Ha 5000 62500")])
    assert kept[0]["role"] == "line_item"


def test_every_kept_region_has_exactly_one_role():
    """The disjoint-roles invariant: a region is line_item XOR metadata."""
    regions = [
        _region("table", "Qty Rate"),
        _region("header", "TAX INVOICE"),
        _region("text", "Bill No: 8316"),
        _region("handwriting", "1250"),
        _region("footnote", "terms apply"),
    ]
    for kept in select_regions(regions):
        assert kept["role"] in ("line_item", "metadata")


@pytest.mark.parametrize(
    "label,expected",
    [("table", "table"), ("handwriting", "handwriting"), ("header", "unrelated_header"),
     ("footer", "unrelated_header"), ("logo", "logo"), ("footnote", "legal_text")],
)
def test_region_label_classification(label, expected):
    assert classify_region_label(label) == expected


def test_unknown_region_label_defaults_to_printed_text():
    """An unfamiliar layout label should get the keyword heuristic rather
    than being silently dropped."""
    assert classify_region_label("some_future_label") == "printed_text"


# --------------------------------------------------------------------------
# Metadata vs line-item text classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line",
    ["TAX INVOICE", "GST NO: 27AAAAA", "Bill No : 8316", "Amount in Words : Three Thousand",
     "Details of Receiver:", "CGST @6.00%", "Grand Total", "IFSC: ABCD0001234"],
)
def test_metadata_phrases_detected(line):
    assert is_metadata_line(line) is True
    assert is_line_item_text(line) is False


@pytest.mark.parametrize("line", ["Site clearing 12.5 Ha 5000 62500", "Description Qty Rate Amount"])
def test_line_item_text_detected(line):
    assert is_line_item_text(line) is True


# --------------------------------------------------------------------------
# Document classification
# --------------------------------------------------------------------------

def test_invoice_classified_from_multiple_signals():
    assert classify_document(["TAX INVOICE GST NO HSN CGST"])["value"] == "invoice"


def test_boq_classified_from_multiple_signals():
    assert classify_document(["SCOPE OF WORK BILL OF QUANTITIES excavation hauling"])["value"] == "boq"


def test_insufficient_signals_returns_unknown():
    """Spec: never force an unknown document into invoice/BOQ."""
    result = classify_document(["Weather was overcast and the team recorded readings."])
    assert result["value"] == "unknown"
    assert result["confidence"] == 0.0
    assert result["candidates"] == []


def test_single_weak_signal_is_not_enough():
    assert classify_document(["a document mentioning hsn once"])["value"] == "unknown"


def test_classifier_runs_on_whole_document_not_per_page():
    """Signals split across pages must still add up to a confident call."""
    assert classify_document(["TAX INVOICE", "GST NO 27AAA", "HSN 640319"])["value"] == "invoice"


def test_non_invoice_boq_document_types_are_representable():
    """Spec: the system must handle arbitrary types without pre-selection, and
    represent multiple candidates with confidence."""
    result = classify_document(["ACCOUNT STATEMENT opening balance debit credit balance"])
    assert result["value"] == "bank_statement", "a bank statement should be identifiable as its own type"
    assert 0.0 < result["confidence"] <= 0.95
    assert any(c["value"] == "bank_statement" for c in result["candidates"])


def test_document_type_is_unknown_on_a_genuine_tie():
    """Two types scoring identically is not a confident call for either —
    surfacing one arbitrarily would be worse than admitting the ambiguity."""
    result = classify_document(["tax invoice gst no scope of work bill of quantities"])
    assert result["value"] == "unknown"
    values = {c["value"] for c in result["candidates"]}
    assert {"invoice", "boq"} <= values


def test_candidates_are_sorted_most_confident_first():
    result = classify_document(["TAX INVOICE GST NO HSN CGST bill of quantities"])
    scores = [c["confidence"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)
