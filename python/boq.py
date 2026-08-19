"""Geometry-based BOQ row reconstruction.

Deliberately NOT an LLM: for structured tables, bbox geometry + column-header
matching is cheaper, deterministic, and more reliable than sending every cell
through a model. The LLM is reserved for the later validation-time step where
a field's value is genuinely ambiguous after this deterministic pass (e.g.
conflicting OCR reads) — it is not used here to "read" the table.
"""

from collections import Counter, defaultdict

COLUMN_ORDER = ["description", "quantity", "unit", "rate", "amount"]

_COLUMN_KEYWORDS = {
    "description": ("description", "particulars", "item", "scope of work"),
    "quantity": ("qty", "quantity"),
    "unit": ("unit", "uom"),
    "rate": ("rate", "unit rate", "unit price", "price"),
    "amount": ("amount", "total", "value"),
}

Y_TOLERANCE = 5  # px; rows whose vertical ranges overlap or are within this gap merge
HEADER_MIN_MATCHED_COLUMNS = 3  # row must label >=3 distinct columns to count as a header


def _match_column_keyword(text: str) -> str | None:
    lower = text.strip().lower()
    for column, keywords in _COLUMN_KEYWORDS.items():
        if any(keyword == lower or keyword in lower for keyword in keywords):
            return column
    return None


def _group_rows_by_y(values: list[dict]) -> list[tuple[int, list[dict]]]:
    """Cluster values into rows per page using bbox y-coordinate proximity:
    a value joins the current row if its top edge falls within the current
    row's vertical span (plus tolerance), otherwise it starts a new row."""
    by_page: dict[int, list[dict]] = defaultdict(list)
    for value in values:
        by_page[value["page"]].append(value)

    rows: list[tuple[int, list[dict]]] = []
    for page in sorted(by_page):
        items = sorted(by_page[page], key=lambda v: v["bbox"][1])
        current: list[dict] = []
        current_y1 = None

        for item in items:
            y0, y1 = item["bbox"][1], item["bbox"][3]
            if current and y0 <= current_y1 + Y_TOLERANCE:
                current.append(item)
                current_y1 = max(current_y1, y1)
            else:
                if current:
                    rows.append((page, current))
                current = [item]
                current_y1 = y1

        if current:
            rows.append((page, current))

    return rows


def _detect_header_bands(row_values: list[dict]) -> dict[str, tuple[float, float]] | None:
    """If this row's cells label >= HEADER_MIN_MATCHED_COLUMNS distinct BOQ
    columns, treat it as a header row and derive an x-coordinate band per
    column from each matched cell's bbox (extended halfway to its neighbors
    so nearby data-row values fall inside the right band)."""
    matched: list[tuple[str, dict]] = []
    for value in row_values:
        column = _match_column_keyword(value["value"])
        if column:
            matched.append((column, value))

    if len({column for column, _ in matched}) < HEADER_MIN_MATCHED_COLUMNS:
        return None

    matched.sort(key=lambda pair: pair[1]["bbox"][0])

    bands: dict[str, tuple[float, float]] = {}
    for i, (column, value) in enumerate(matched):
        x0, x1 = value["bbox"][0], value["bbox"][2]
        lo = -float("inf") if i == 0 else (matched[i - 1][1]["bbox"][2] + x0) / 2
        hi = float("inf") if i == len(matched) - 1 else (x1 + matched[i + 1][1]["bbox"][0]) / 2
        bands[column] = (lo, hi)

    return bands


def _assign_by_bands(
    row_values: list[dict], bands: dict[str, tuple[float, float]]
) -> dict[str, list[dict]]:
    assigned: dict[str, list[dict]] = defaultdict(list)
    for value in row_values:
        center = (value["bbox"][0] + value["bbox"][2]) / 2
        best_column = None
        best_distance = None
        for column, (lo, hi) in bands.items():
            if lo <= center < hi:
                best_column = column
                break
            # track nearest band as a fallback for values that fall just
            # outside every band (e.g. a slightly misdetected header)
            distance = min(abs(center - lo), abs(center - hi))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_column = column
        assigned[best_column].append(value)
    return assigned


def _assign_by_position(row_values: list[dict]) -> dict[str, list[dict]]:
    """No header detected for this page: fall back to left-to-right position
    order across the fixed column sequence."""
    ordered = sorted(row_values, key=lambda v: v["bbox"][0])
    assigned: dict[str, list[dict]] = defaultdict(list)
    for i, value in enumerate(ordered):
        column = COLUMN_ORDER[i] if i < len(COLUMN_ORDER) else COLUMN_ORDER[-1]
        assigned[column].append(value)
    return assigned


def _merge_field(values: list[dict], page: int) -> dict:
    if not values:
        return {"value": "", "source": "pymupdf", "confidence": 0.0, "page": page, "bbox": [0, 0, 0, 0]}

    ordered = sorted(values, key=lambda v: v["bbox"][0])
    merged_value = " ".join(v["value"] for v in ordered)
    merged_confidence = sum(v["confidence"] for v in ordered) / len(ordered)
    merged_bbox = [
        min(v["bbox"][0] for v in ordered),
        min(v["bbox"][1] for v in ordered),
        max(v["bbox"][2] for v in ordered),
        max(v["bbox"][3] for v in ordered),
    ]
    # a field spanning spans from more than one engine still needs a single
    # source tag; take the majority engine among the spans that make it up
    dominant_source = Counter(v["source"] for v in ordered).most_common(1)[0][0]

    return {
        "value": merged_value,
        "source": dominant_source,
        "confidence": merged_confidence,
        "page": page,
        "bbox": merged_bbox,
    }


def build_boq(extracted_values: list[dict]) -> list[dict]:
    """Reconstruct BOQ rows from a flat list of ExtractedValue-shaped dicts
    (mixed PyMuPDF/PaddleOCR/Tesseract) using bbox geometry only — no LLM."""
    rows = _group_rows_by_y(extracted_values)

    header_bands_by_page: dict[int, dict[str, tuple[float, float]] | None] = {}
    boq_rows: list[dict] = []

    for page, row_values in rows:
        if page not in header_bands_by_page:
            header_bands_by_page[page] = _detect_header_bands(row_values)
            if header_bands_by_page[page] is not None:
                continue  # this row IS the header row itself; skip as data

        bands = header_bands_by_page[page]
        assigned = _assign_by_bands(row_values, bands) if bands else _assign_by_position(row_values)

        boq_rows.append(
            {column: _merge_field(assigned.get(column, []), page) for column in COLUMN_ORDER}
        )

    return boq_rows
