"""Phase 1/2: canonical evidence enrichment + geometric reading order.

Both are purely additive — existing role/category/bbox/etc. keys must
survive untouched.
"""

from evidence import attach_evidence_metadata, to_evidence
from reading_order import assign_reading_order


def _v(value, x0, y0, x1, y1, *, category="table", role="line_item", page=1):
    return {
        "value": value, "source": "paddleocr", "confidence": 0.9, "page": page,
        "bbox": [float(x0), float(y0), float(x1), float(y1)], "category": category, "role": role,
    }


# --------------------------------------------------------------------------
# Evidence enrichment
# --------------------------------------------------------------------------

def test_existing_keys_survive_untouched():
    original = _v("Bread", 0, 0, 10, 10)
    enriched = to_evidence(original)
    for key, val in original.items():
        assert enriched[key] == val


def test_new_fields_are_added():
    enriched = to_evidence(_v("Bread", 0, 0, 10, 10))
    assert enriched["id"]
    assert enriched["normalized_value"] == "Bread"
    assert enriched["region_type"] == "table"
    assert enriched["semantic_role"] is None
    assert enriched["language"] is None
    assert "reading_order" in enriched


def test_region_type_derived_from_category():
    assert to_evidence(_v("x", 0, 0, 1, 1, category="handwriting"))["region_type"] == "handwriting"
    assert to_evidence(_v("x", 0, 0, 1, 1, category="printed_text"))["region_type"] == "text"
    assert to_evidence(_v("x", 0, 0, 1, 1, category="unrelated_header"))["region_type"] == "header"
    assert to_evidence(_v("x", 0, 0, 1, 1, category="logo"))["region_type"] == "image"


def test_unfamiliar_category_maps_to_unknown_not_a_crash():
    assert to_evidence(_v("x", 0, 0, 1, 1, category="some_future_thing"))["region_type"] == "unknown"


def test_ids_are_unique_across_a_batch():
    values = [_v(f"v{i}", 0, 0, 1, 1) for i in range(20)]
    ids = [e["id"] for e in attach_evidence_metadata(values)]
    assert len(set(ids)) == len(ids)


def test_batch_helper_preserves_order_and_count():
    values = [_v("a", 0, 0, 1, 1), _v("b", 0, 0, 1, 1)]
    enriched = attach_evidence_metadata(values)
    assert [e["value"] for e in enriched] == ["a", "b"]


# --------------------------------------------------------------------------
# Reading order
# --------------------------------------------------------------------------

def test_single_column_top_to_bottom():
    values = [_v("third", 0, 200, 100, 220), _v("first", 0, 0, 100, 20), _v("second", 0, 100, 100, 120)]
    assign_reading_order(values)
    ordered = sorted(values, key=lambda v: v["reading_order"])
    assert [v["value"] for v in ordered] == ["first", "second", "third"]


def test_two_column_layout_orders_left_column_fully_before_right():
    """Mirrors the multi_column fixture: left column top-to-bottom, then
    right column top-to-bottom — never interleaved by raw y position alone."""
    left = [_v("L1", 100, 0, 300, 20), _v("L2", 100, 100, 300, 120), _v("L3", 100, 200, 300, 220)]
    right = [_v("R1", 900, 0, 1100, 20), _v("R2", 900, 100, 1100, 120), _v("R3", 900, 200, 1100, 220)]
    values = right + left  # deliberately interleaved input order
    assign_reading_order(values)
    ordered = [v["value"] for v in sorted(values, key=lambda v: v["reading_order"])]
    assert ordered == ["L1", "L2", "L3", "R1", "R2", "R3"]


def test_reading_order_is_deterministic_and_covers_every_value():
    values = [_v(f"v{i}", i * 10, i * 5, i * 10 + 5, i * 5 + 5) for i in range(8)]
    assign_reading_order(values)
    orders = sorted(v["reading_order"] for v in values)
    assert orders == list(range(8))


def test_empty_input_does_not_crash():
    assert assign_reading_order([]) == []
