"""Geometry-based line-item reconstruction — generalized from BOQ-only rows
to invoices/receipts too (LineItem: itemCode?/description/quantity/unit?/
rate/amount/taxRate?/taxAmount?).

Deliberately NOT an LLM: for structured tables, bbox geometry + column-header
matching is cheaper, deterministic, and more reliable than sending every cell
through a model. The LLM is reserved for the later validation-time step where
a field's value is genuinely ambiguous after this deterministic pass — it is
not used here to "read" the table.

Callers MUST pre-filter to role=="line_item" values only (see layout.py /
pymupdf_parser.py / metadata_extractor.is_line_item_text) — header, receiver,
and totals-footer text must never reach this module.
"""

from collections import Counter, defaultdict

NUMERIC_COLUMNS = ("quantity", "rate", "amount", "taxRate", "taxAmount")
OPTIONAL_COLUMNS = ("itemCode", "unit", "taxRate", "taxAmount")
# Always present in output rows (mirrors LineItem's non-optional fields).
CORE_COLUMN_ORDER = ["description", "quantity", "rate", "amount"]
# Legacy 5-column guess used only when NO header row could be identified at
# all (position-fallback) — the classic BOQ layout assumption.
POSITION_FALLBACK_ORDER = ["description", "quantity", "unit", "rate", "amount"]

_COLUMN_KEYWORDS = {
    "description": ("description", "particulars", "item", "scope of work"),
    "quantity": ("qty", "quantity"),
    "unit": ("unit", "uom"),
    "rate": ("rate", "unit rate", "unit price", "price"),
    "amount": ("amount", "total", "value"),
    "itemCode": ("hsn", "hsn code", "item code", "sku"),
}

Y_TOLERANCE = 5  # px; rows whose vertical ranges overlap or are within this gap merge
HEADER_MIN_MATCHED_COLUMNS = 3  # loose-text header row must label >=3 distinct columns
# A detected TABLE region's header row is judged by how many of our known
# columns it labels: 0 -> not a line-item table at all (e.g. a GST/tax
# summary box) -> route to metadata instead; 1 -> attempted but too
# uncertain to trust field assignment -> "incomplete"; >=2 -> proceed.
TABLE_HEADER_METADATA_THRESHOLD = 0
TABLE_HEADER_INCOMPLETE_THRESHOLD = 1


def _match_column_keyword(text: str) -> str | None:
    lower = text.strip().lower()
    for column, keywords in _COLUMN_KEYWORDS.items():
        if any(keyword == lower or keyword in lower for keyword in keywords):
            return column
    return None


def _numeric_or_string(column: str, text: str) -> float | str:
    if column not in NUMERIC_COLUMNS:
        return text
    cleaned = text.strip().replace(",", "").replace("$", "")
    try:
        return float(cleaned)
    except ValueError:
        return text  # left as the raw string so numeric_parse_failure can catch it downstream


def _merge_field(column: str, values: list[dict], page: int) -> dict:
    if not values:
        return {"value": "", "source": "pymupdf", "confidence": 0.0, "page": page, "bbox": [0, 0, 0, 0]}

    ordered = sorted(values, key=lambda v: v["bbox"][0])
    merged_text = " ".join(v["value"] for v in ordered)
    merged_confidence = sum(v["confidence"] for v in ordered) / len(ordered)
    merged_bbox = [
        min(v["bbox"][0] for v in ordered),
        min(v["bbox"][1] for v in ordered),
        max(v["bbox"][2] for v in ordered),
        max(v["bbox"][3] for v in ordered),
    ]
    dominant_source = Counter(v["source"] for v in ordered).most_common(1)[0][0]

    return {
        "value": _numeric_or_string(column, merged_text),
        "source": dominant_source,
        "confidence": merged_confidence,
        "page": page,
        "bbox": merged_bbox,
    }


def _empty_row(page: int, columns: list[str]) -> dict:
    return {column: _merge_field(column, [], page) for column in columns}


def _group_rows_by_y(values: list[dict]) -> list[list[dict]]:
    """Cluster values into rows by bbox y-coordinate proximity, assuming all
    values already belong to the same page/region."""
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


def _detect_header_row(rows: list[list[dict]], min_matched: int) -> tuple[int, dict[str, tuple[float, float]]] | None:
    """Scan every row (not just the first) for one that labels enough known
    columns to be the header. Returns (row_index, column_x_bands) or None."""
    for row_index, row_values in enumerate(rows):
        matched: list[tuple[str, dict]] = []
        for value in row_values:
            column = _match_column_keyword(str(value["value"]))
            if column:
                matched.append((column, value))

        distinct = {column for column, _ in matched}
        if len(distinct) < min_matched:
            continue

        matched.sort(key=lambda pair: pair[1]["bbox"][0])
        bands: dict[str, tuple[float, float]] = {}
        for i, (column, value) in enumerate(matched):
            x0, x1 = value["bbox"][0], value["bbox"][2]
            lo = -float("inf") if i == 0 else (matched[i - 1][1]["bbox"][2] + x0) / 2
            hi = float("inf") if i == len(matched) - 1 else (x1 + matched[i + 1][1]["bbox"][0]) / 2
            bands[column] = (lo, hi)
        return row_index, bands

    return None


def _assign_by_bands(row_values: list[dict], bands: dict[str, tuple[float, float]]) -> dict[str, list[dict]]:
    assigned: dict[str, list[dict]] = defaultdict(list)
    for value in row_values:
        center = (value["bbox"][0] + value["bbox"][2]) / 2
        best_column, best_distance = None, None
        for column, (lo, hi) in bands.items():
            if lo <= center < hi:
                best_column = column
                break
            distance = min(abs(center - lo), abs(center - hi))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_column = column
        assigned[best_column].append(value)
    return assigned


def _assign_by_position(row_values: list[dict]) -> dict[str, list[dict]]:
    """No header detected: fall back to left-to-right position order across
    the classic 5-column BOQ layout guess."""
    ordered = sorted(row_values, key=lambda v: v["bbox"][0])
    assigned: dict[str, list[dict]] = defaultdict(list)
    for i, value in enumerate(ordered):
        column = POSITION_FALLBACK_ORDER[i] if i < len(POSITION_FALLBACK_ORDER) else POSITION_FALLBACK_ORDER[-1]
        assigned[column].append(value)
    return assigned


def _columns_for(bands: dict[str, tuple[float, float]] | None) -> list[str]:
    """Which output columns to emit. Optional columns (unit/itemCode/tax*)
    are included only when actually detected via a header band — omitted
    entirely otherwise, per LineItem's optional fields."""
    if not bands:
        return POSITION_FALLBACK_ORDER
    columns = list(CORE_COLUMN_ORDER)
    for optional in OPTIONAL_COLUMNS:
        if optional in bands and optional not in columns:
            columns.append(optional)
    return columns


def _build_from_table_region(region_id: str, values: list[dict]) -> tuple[list[dict], list[str]]:
    """One detected TABLE region -> its own header search + column mapping,
    confined entirely to this region's own rows. Returns (rows, leftover
    text lines to route to metadata — used when this 'table' turns out to be
    a non-line-item summary box, e.g. a GST breakdown)."""
    page = values[0]["page"]
    rows = _group_rows_by_y(values)

    header = _detect_header_row(rows, min_matched=TABLE_HEADER_INCOMPLETE_THRESHOLD + 1)
    if header is None:
        matched_count = 0
    else:
        header_index, bands = header
        matched_count = len(bands)

    if matched_count <= TABLE_HEADER_METADATA_THRESHOLD:
        # Not a line-item table at all (e.g. a tax/GST summary box) — hand
        # its text to metadata extraction instead of fabricating rows.
        leftover = [" ".join(v["value"] for v in sorted(row, key=lambda v: v["bbox"][0])) for row in rows]
        return [], leftover

    if matched_count <= TABLE_HEADER_INCOMPLETE_THRESHOLD:
        # Found *a* header-like row but not enough of our known columns to
        # trust field assignment — honest "incomplete" rather than a guess.
        data_rows = rows[header_index + 1 :] if header else rows
        line_items = []
        for row_values in data_rows:
            raw_text = " ".join(v["value"] for v in sorted(row_values, key=lambda v: v["bbox"][0]))
            row = _empty_row(page, CORE_COLUMN_ORDER)
            row["description"] = _merge_field("description", row_values, page)
            row["description"]["value"] = raw_text
            row["_status_override"] = "incomplete"
            line_items.append(row)
        return line_items, []

    data_rows = rows[header_index + 1 :]
    columns = _columns_for(bands)
    line_items = []
    for row_values in data_rows:
        assigned = _assign_by_bands(row_values, bands)
        line_items.append({column: _merge_field(column, assigned.get(column, []), page) for column in columns})
    return line_items, []


def _build_from_loose_text(values: list[dict]) -> list[dict]:
    """Line-item-candidate text NOT inside any detected table region (plain
    paragraph-style BOQ lines, or handwriting) — the original y-clustering +
    header-band-or-position approach, per page."""
    by_page: dict[int, list[dict]] = defaultdict(list)
    for value in values:
        by_page[value["page"]].append(value)

    line_items: list[dict] = []
    for page in sorted(by_page):
        rows = _group_rows_by_y(by_page[page])
        header = _detect_header_row(rows, min_matched=HEADER_MIN_MATCHED_COLUMNS)
        header_index = header[0] if header else None
        bands = header[1] if header else None
        columns = _columns_for(bands)

        for row_index, row_values in enumerate(rows):
            if header_index is not None and row_index == header_index:
                continue  # this row IS the header row itself; skip as data
            assigned = _assign_by_bands(row_values, bands) if bands else _assign_by_position(row_values)
            line_items.append(
                {column: _merge_field(column, assigned.get(column, []), page) for column in columns}
            )

    return line_items


def build_line_items(values: list[dict]) -> tuple[list[dict], list[str]]:
    """Reconstruct line items from role=="line_item" ExtractedValue-shaped
    dicts (mixed PyMuPDF/PaddleOCR/Tesseract) using bbox geometry only.

    Returns (line_items, leftover_metadata_texts) — the second element
    holds text from table-shaped regions that turned out NOT to be
    line-item tables (e.g. a GST summary box), for extract_metadata() to
    scan for totals.
    """
    by_region: dict[str, list[dict]] = defaultdict(list)
    loose: list[dict] = []

    for value in values:
        if value.get("category") == "table":
            by_region[value.get("region_id", "unknown")].append(value)
        else:
            loose.append(value)

    line_items: list[dict] = []
    leftover_texts: list[str] = []

    for region_id, region_values in by_region.items():
        rows, leftover = _build_from_table_region(region_id, region_values)
        line_items.extend(rows)
        leftover_texts.extend(leftover)

    line_items.extend(_build_from_loose_text(loose))

    return line_items, leftover_texts
