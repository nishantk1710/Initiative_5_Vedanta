"""Deterministic table reconstruction from bbox geometry.

Values are hand-placed so the geometry is explicit and the expected column
mapping is unambiguous — no OCR involved.
"""

import pytest

from line_items import build_line_items


def _v(text, x0, y0, x1, y1, *, page=1, category="table", region_id="1:table:0",
       source="paddleocr", confidence=0.97):
    return {
        "value": text,
        "source": source,
        "confidence": confidence,
        "page": page,
        "bbox": [float(x0), float(y0), float(x1), float(y1)],
        "role": "line_item",
        "category": category,
        "region_id": region_id,
    }


def _grid(header: list[str], rows: list[list[str]], *, category="table", region_id="1:table:0"):
    """Lay a table out on a synthetic grid: 5 columns, 40px row pitch."""
    xs = [(0, 200), (250, 350), (400, 500), (550, 700), (750, 900)]
    out = []
    for i, h in enumerate(header):
        x0, x1 = xs[i]
        out.append(_v(h, x0, 0, x1, 20, category=category, region_id=region_id))
    for r, cells in enumerate(rows, start=1):
        y = r * 40
        for i, cell in enumerate(cells):
            if cell == "":
                continue
            x0, x1 = xs[i]
            out.append(_v(cell, x0, y, x1, y + 20, category=category, region_id=region_id))
    return out


def test_columns_mapped_from_header_text_not_position():
    """Header order is shuffled; mapping must follow the header words."""
    values = _grid(
        ["Description", "Amount", "Quantity", "Rate", "Unit"],
        [["Site clearing", "62500", "12.5", "5000", "Ha"]],
    )
    items, _, _ = build_line_items(values)
    assert len(items) == 1
    r = items[0]
    assert r["description"]["value"] == "Site clearing"
    assert r["quantity"]["value"] == 12.5
    assert r["rate"]["value"] == 5000.0
    assert r["amount"]["value"] == 62500.0
    assert r["unit"]["value"] == "Ha"


def test_header_row_is_not_emitted_as_data():
    values = _grid(
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [["Site clearing", "12.5", "Ha", "5000", "62500"]],
    )
    items, _, _ = build_line_items(values)
    assert len(items) == 1
    assert items[0]["description"]["value"] == "Site clearing"


def test_numeric_columns_are_coerced_to_numbers():
    values = _grid(
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [["Widget", "1,250", "pcs", "2.50", "3125"]],
    )
    items, _, _ = build_line_items(values)
    assert items[0]["quantity"]["value"] == 1250.0
    assert items[0]["rate"]["value"] == 2.5
    assert isinstance(items[0]["unit"]["value"], str)


def test_unparseable_numeric_is_left_as_raw_string():
    """So validator.py can flag numeric_parse_failure rather than us dropping
    a value the engine really did read."""
    values = _grid(
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [["Widget", "12S0", "pcs", "10", "100"]],
    )
    items, _, _ = build_line_items(values)
    assert items[0]["quantity"]["value"] == "12S0"


def test_optional_columns_omitted_when_header_absent():
    """Spec 17: no Unit column at all when the table has none."""
    values = _grid(["Description", "Quantity", "Rate", "Amount"],
                   [["Widget", "2", "10", "20"]])
    items, _, _ = build_line_items(values)
    assert "unit" not in items[0]
    assert "itemCode" not in items[0]


def test_item_code_column_recognised():
    values = _grid(["HSN", "Description", "Quantity", "Rate", "Amount"],
                   [["640319", "Footwear", "1", "699", "699"]])
    items, _, _ = build_line_items(values)
    assert items[0]["itemCode"]["value"] == "640319"


def test_multiple_data_rows(  ):
    values = _grid(
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [
            ["Site clearing", "12.5", "Ha", "5000", "62500"],
            ["Overburden removal", "45000", "m3", "12", "540000"],
            ["Haul road", "3.2", "km", "25000", "80000"],
        ],
    )
    items, _, _ = build_line_items(values)
    assert [r["description"]["value"] for r in items] == [
        "Site clearing", "Overburden removal", "Haul road",
    ]


def test_provenance_is_preserved_per_field():
    """Spec 22: every value traceable to page + bbox + source."""
    values = _grid(["Description", "Quantity", "Unit", "Rate", "Amount"],
                   [["Site clearing", "12.5", "Ha", "5000", "62500"]])
    items, _, _ = build_line_items(values)
    for key in ("description", "quantity", "rate", "amount"):
        f = items[key] if isinstance(items, dict) else items[0][key]
        assert f["source"] == "paddleocr"
        assert f["page"] == 1
        assert len(f["bbox"]) == 4
        assert any(f["bbox"]), "bbox must not be all zeros for an extracted value"


def test_table_with_no_recognisable_headers_is_not_line_items():
    """Spec 19: zero matched header columns -> not a line-item table. Its text
    is handed back for metadata rather than fabricated into rows."""
    values = _grid(["Alpha", "Beta", "Gamma", "Delta", "Epsilon"],
                   [["foo", "1", "x", "2", "3"]])
    items, leftover, non_line_item = build_line_items(values)
    assert items == []
    assert leftover, "unmatched table text should be returned for metadata scanning"


def test_table_with_one_recognisable_header_is_incomplete():
    """Spec 20: an honest 'we found a table but could not parse its columns'
    beats guessing at field assignment."""
    values = _grid(["Description", "Alpha", "Beta", "Gamma", "Delta"],
                   [["widget", "1", "x", "2", "3"]])
    items, _, _ = build_line_items(values)
    assert items, "rows should still be reported"
    assert all(r.get("_status_override") == "incomplete" for r in items)


def test_loose_text_without_header_is_marked_position_guessed():
    """Blind left-to-right assignment must be flagged so pipeline.py can
    prefer the LLM fallback over trusting it."""
    values = [
        _v("Excavation", 0, 100, 200, 120, category="text", region_id="1:text:0"),
        _v("500", 250, 100, 350, 120, category="text", region_id="1:text:0"),
        _v("1250", 400, 100, 500, 120, category="text", region_id="1:text:0"),
    ]
    items, _, _ = build_line_items(values)
    assert items
    assert all(r.get("_position_guessed") for r in items)


def test_rows_from_separate_pages_do_not_merge():
    page1 = _grid(["Description", "Quantity", "Unit", "Rate", "Amount"],
                  [["Site clearing", "12.5", "Ha", "5000", "62500"]])
    page2 = [dict(v, page=2, region_id="2:table:0") for v in
             _grid(["Description", "Quantity", "Unit", "Rate", "Amount"],
                   [["Blasting", "300", "holes", "800", "240000"]])]
    items, _, _ = build_line_items(page1 + page2)
    pages = {r["description"]["page"] for r in items}
    assert pages == {1, 2}
    assert len(items) == 2
