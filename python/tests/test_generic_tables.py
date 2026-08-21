"""Generic physical table reconstruction + semantic tagging (Phase 5).

A table region whose header doesn't match any known BOQ/invoice column
keyword is not proof it has no structure — a bank statement's
"Date | Description | Debit | Credit | Balance" table must still be
reconstructed, just without being forced into invoice_items semantics.
"""

from generic_tables import reconstruct_physical_table
from line_items import build_line_items
from table_semantics import classify_table_semantics


def _v(text, x0, y0, x1, y1, *, page=1, region_id="1:table:0"):
    return {
        "value": text, "source": "paddleocr", "confidence": 0.9,
        "page": page, "bbox": [float(x0), float(y0), float(x1), float(y1)],
        "role": "line_item", "category": "table", "region_id": region_id,
    }


def _grid(header, rows, region_id="1:table:0"):
    xs = [(0, 200), (250, 400), (450, 600), (650, 800), (850, 1000)]
    out = []
    for i, h in enumerate(header):
        x0, x1 = xs[i]
        out.append(_v(h, x0, 0, x1, 20, region_id=region_id))
    for r, cells in enumerate(rows, start=1):
        y = r * 40
        for i, cell in enumerate(cells):
            x0, x1 = xs[i]
            out.append(_v(cell, x0, y, x1, y + 20, region_id=region_id))
    return out


# --------------------------------------------------------------------------
# reconstruct_physical_table: shape only, no keyword assumptions
# --------------------------------------------------------------------------

def test_reconstructs_headers_and_rows_from_geometry_alone():
    values = _grid(
        ["Date", "Description", "Debit", "Credit", "Balance"],
        [["01/04/2026", "Salary credit", "", "50000", "150000"]],
    )
    table = reconstruct_physical_table("1:table:0", values)
    assert table["headers"] == ["Date", "Description", "Debit", "Credit", "Balance"]
    assert table["row_count"] == 1
    assert table["rows"][0][1] == "Salary credit"


def test_empty_region_returns_none():
    assert reconstruct_physical_table("x", []) is None


def test_table_bbox_covers_every_cell():
    values = _grid(["A", "B"], [["1", "2"]])
    table = reconstruct_physical_table("1:table:0", values)
    x0, y0, x1, y1 = table["bbox"]
    for v in values:
        vx0, vy0, vx1, vy1 = v["bbox"]
        assert x0 <= vx0 and y0 <= vy0 and x1 >= vx1 and y1 >= vy1


# --------------------------------------------------------------------------
# classify_table_semantics: confident-or-unknown, never a forced label
# --------------------------------------------------------------------------

def test_bank_transaction_headers_are_tagged_correctly():
    result = classify_table_semantics(["Date", "Description", "Debit", "Credit", "Balance"])
    assert result["value"] == "bank_transactions"
    assert result["confidence"] > 0.0


def test_invoice_headers_are_tagged_correctly():
    result = classify_table_semantics(["Description", "Qty", "Rate", "Amount"])
    assert result["value"] == "invoice_items"


def test_unrecognised_headers_stay_unknown_not_forced():
    result = classify_table_semantics(["Alpha", "Beta", "Gamma"])
    assert result["value"] == "unknown"
    assert result["confidence"] == 0.0


def test_single_weak_signal_is_not_enough_to_tag_a_role():
    result = classify_table_semantics(["Amount", "Alpha", "Beta"])
    assert result["value"] == "unknown"


# --------------------------------------------------------------------------
# build_line_items: non-invoice tables surface their raw values, not just
# discarded leftover text
# --------------------------------------------------------------------------

def test_non_line_item_table_values_are_surfaced_for_generic_reconstruction():
    values = _grid(
        ["Date", "Narration", "Debit", "Credit", "Balance"],
        [["01/04/2026", "Salary credit", "", "50000", "150000"]],
        region_id="1:table:7",
    )
    line_items, leftover, non_line_item_tables = build_line_items(values)
    assert line_items == []
    assert leftover
    assert "1:table:7" in non_line_item_tables
    assert len(non_line_item_tables["1:table:7"]) == len(values)


def test_real_line_item_table_produces_no_generic_leftover():
    values = _grid(
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [["Site clearing", "12.5", "Ha", "5000", "62500"]],
    )
    line_items, leftover, non_line_item_tables = build_line_items(values)
    assert line_items
    assert non_line_item_tables == {}
