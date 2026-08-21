"""Geometric reading order for a single page's evidence.

Deliberately not "sort by OCR output order" — PaddleOCR's own emission order
does not reliably follow a multi-column layout, and PyMuPDF's block order can
follow PDF content-stream order rather than visual order. This derives order
purely from bbox geometry, the same coordinate space every other stage in
this pipeline already shares.

Approach: detect column bands via a gap-based split on x-midpoints (not
k-means — the number of columns isn't known in advance and a simple largest-
gap-threshold split is enough for the common 1- and 2-column cases this
pipeline actually needs to handle), then order left-column-top-to-bottom
before right-column-top-to-bottom, and within a column purely top-to-bottom.
"""

# A gap between adjacent x-midpoints must be at least this fraction of the
# page's overall x-spread to be treated as a column boundary rather than
# ordinary word/cell spacing within one column.
MIN_COLUMN_GAP_FRACTION = 0.15

Y_TOLERANCE = 8  # px; treat values within this vertical band as the "same" row for stable ordering


def _x_mid(bbox: list[float]) -> float:
    return (bbox[0] + bbox[2]) / 2


def _detect_column_bands(values: list[dict]) -> list[tuple[float, float]]:
    """Return [(x_start, x_end), ...] column bands, left to right. A single
    band covering everything means "no multi-column split detected"."""
    if not values:
        return []

    xs = sorted(_x_mid(v["bbox"]) for v in values)
    x_min, x_max = xs[0], xs[-1]
    spread = x_max - x_min
    if spread <= 0:
        return [(x_min - 1, x_max + 1)]

    min_gap = spread * MIN_COLUMN_GAP_FRACTION
    bands: list[tuple[float, float]] = []
    band_start = xs[0]
    prev = xs[0]
    for x in xs[1:]:
        if x - prev >= min_gap:
            bands.append((band_start, prev))
            band_start = x
        prev = x
    bands.append((band_start, prev))
    return bands


def _band_index(x_mid: float, bands: list[tuple[float, float]]) -> int:
    for i, (start, end) in enumerate(bands):
        if x_mid <= end + 1e-6:
            return i
    return len(bands) - 1


def assign_reading_order(values: list[dict]) -> list[dict]:
    """Mutates each value in place, setting `reading_order` to its 0-based
    position. `values` must all belong to one page — call once per page."""
    if not values:
        return values

    bands = _detect_column_bands(values)

    def sort_key(v: dict):
        band = _band_index(_x_mid(v["bbox"]), bands)
        y = v["bbox"][1]
        # snap y to a coarse bucket so near-identical rows don't get
        # reordered by sub-pixel jitter, while still sorting top-to-bottom
        y_bucket = round(y / Y_TOLERANCE)
        x = v["bbox"][0]
        return (band, y_bucket, x)

    ordered = sorted(values, key=sort_key)
    for i, v in enumerate(ordered):
        v["reading_order"] = i
    return values
