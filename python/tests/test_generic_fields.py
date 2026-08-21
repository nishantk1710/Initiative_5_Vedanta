"""Generic key-value field discovery (Phase 6) — evidence-grounded, no
fixed field list, no null padding for absent fields."""

from generic_fields import extract_generic_fields


def test_extracts_simple_label_value_lines():
    fields = extract_generic_fields(["Name: Jordan Rivera", "Phone: 555-0100"])
    assert fields["name"]["value"] == "Jordan Rivera"
    assert fields["phone"]["value"] == "555-0100"


def test_multi_word_label_is_camel_cased():
    fields = extract_generic_fields(["Account Number: 1234567890"])
    assert "accountNumber" in fields
    assert fields["accountNumber"]["value"] == "1234567890"


def test_absent_field_produces_no_key_at_all():
    """The no-hallucination guarantee: fields never appear as null."""
    fields = extract_generic_fields(["Just some prose with no labels here."])
    assert fields == {}


def test_labels_already_owned_by_metadata_extractor_are_skipped():
    fields = extract_generic_fields(["GST No: 27AAAAA0000A1Z5", "Invoice Number: INV-42"])
    assert fields == {}


def test_first_occurrence_wins_over_a_later_duplicate_label():
    fields = extract_generic_fields(["Status: Active", "Status: Inactive"])
    assert fields["status"]["value"] == "Active"


def test_lines_without_a_colon_or_dash_are_ignored():
    fields = extract_generic_fields(["This is a plain sentence without any label shape"])
    assert fields == {}


def test_every_field_carries_source_and_confidence():
    fields = extract_generic_fields(["Employer: Acme Corp"])
    assert fields["employer"]["source"] == "regex"
    assert 0.0 < fields["employer"]["confidence"] < 1.0
