"""Generic physical table reconstruction — geometry only, no opinion about
what a table MEANS.

line_items.py already reconstructs BOQ/invoice tables extremely well by
matching column headers against a known keyword set. But a table region
whose header doesn't match any of those keywords isn't proof that it has no
real structure — it might be a bank statement ("Date | Description | Debit
| Credit | Balance"), an attendance sheet, an inventory log, or something
else entirely. This module answers only "what is this table's physical
shape" (rows, columns, header text) using the same bbox-geometry approach as
line_items.py, but WITHOUT assuming the header cells name any particular
known field. Deciding what the table means is a separate, later question —
see table_semantics.py for a lightweight, still-deterministic first guess,
and the LLM-backed interpreter for anything that guess can't confidently tag.
"""

Y_TOLERANCE = 5


def _group_rows_by_y(values: list[dict]) -> list[list[dict]]:
    items = sorted(values, key=lambda v: v["bbox"][1])
    rows: list[list[dict]] = []
    current: list[dict] = []
    current_y1 = None

    for item in items:
        y0, y1 = item["bbox"][1], item["bbox"][3]
        if current and y0 <= current_y1 + Y_TOLERANCE:
            current.append(item)
            current_y1 = max(current_y1, y1)
        else:
            if current:
                rows.append(current)
            current = [item]
            current_y1 = y1
    if current:
        rows.append(current)

    return rows


def _column_bands_from_row(row_values: list[dict]) -> list[dict]:
    """Derive column x-bands purely from the horizontal gaps between this
    row's own cells — no keyword knowledge of what any cell says."""
    ordered = sorted(row_values, key=lambda v: v["bbox"][0])
    bands = []
    for i, value in enumerate(ordered):
        x0, x1 = value["bbox"][0], value["bbox"][2]
        lo = float("-inf") if i == 0 else (ordered[i - 1]["bbox"][2] + x0) / 2
        hi = float("inf") if i == len(ordered) - 1 else (x1 + ordered[i + 1]["bbox"][0]) / 2
        bands.append({"lo": lo, "hi": hi, "header_text": str(value["value"]).strip()})
    return bands


def _assign_to_bands(row_values: list[dict], bands: list[dict]) -> list[str]:
    cells: list[dict | None] = [None] * len(bands)
    for value in row_values:
        center = (value["bbox"][0] + value["bbox"][2]) / 2
        best_i, best_dist = 0, None
        for i, band in enumerate(bands):
            if band["lo"] <= center < band["hi"]:
                best_i, best_dist = i, None
                break
            dist = min(abs(center - band["lo"]), abs(center - band["hi"]))
            if best_dist is None or dist < best_dist:
                best_dist, best_i = dist, i
        existing = cells[best_i]
        cells[best_i] = value if existing is None else {**existing, "value": f'{existing["value"]} {value["value"]}'}
    return [str(c["value"]) if c else "" for c in cells]


def reconstruct_physical_table(table_id: str, values: list[dict]) -> dict | None:
    """Pure geometry: cluster the region's values into rows, treat the
    topmost row as the header row, and derive column bands from its own
    cell positions. Returns None for an empty region.

    Deliberately naive about whether the top row IS a real header (unlike
    line_items.py's keyword-driven search across every row) — this
    primitive only reconstructs shape; a caller that already knows the
    domain (line_items.py) is free to search more cleverly for its own
    semantic header. This is the fallback shape-reconstruction for tables
    that search didn't recognize at all.
    """
    if not values:
        return None

    page = values[0]["page"]
    rows = _group_rows_by_y(values)
    if not rows:
        return None

    header_row = rows[0]
    bands = _column_bands_from_row(header_row)
    headers = [b["header_text"] for b in bands]

    data_rows = [_assign_to_bands(row_values, bands) for row_values in rows[1:]]

    all_bbox = [v["bbox"] for v in values]
    table_bbox = [
        min(b[0] for b in all_bbox),
        min(b[1] for b in all_bbox),
        max(b[2] for b in all_bbox),
        max(b[3] for b in all_bbox),
    ]

    return {
        "table_id": table_id,
        "page": page,
        "bbox": table_bbox,
        "headers": headers,
        "rows": data_rows,
        "row_count": len(data_rows),
        # Each column's [lo, hi] x-band, in the SAME order as headers —
        # exposed (not just used internally) so continuation.py can compare
        # column positions across pages without re-deriving them from rows.
        "column_bounds": [[b["lo"], b["hi"]] for b in bands],
    }
