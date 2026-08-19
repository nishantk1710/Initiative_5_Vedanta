"""Deterministic validation rules for BOQ rows/fields.

NOTE: the confidence bands and arithmetic tolerance below are a starting
point, not calibrated against real mining SOWs — only against the three
bundled dummy samples. Re-tune these constants once real documents are
available.
"""

NUMERIC_FIELDS = ("quantity", "rate", "amount")
REQUIRED_FIELDS = ("description", "quantity", "unit")

ARITHMETIC_RELATIVE_TOLERANCE = 0.02  # 2% — absorbs OCR/rounding noise
ARITHMETIC_ABSOLUTE_TOLERANCE = 1.0  # floor so near-zero amounts aren't over-flagged

CONFIDENCE_ACCEPT_THRESHOLD = 0.85
CONFIDENCE_REVIEW_THRESHOLD = 0.60

_STATUS_SEVERITY = {"valid": 0, "review": 1, "ambiguous": 2}


def parse_numeric(raw_value) -> float | None:
    if raw_value is None:
        return None
    cleaned = str(raw_value).strip().replace(",", "").replace("$", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def confidence_band(confidence: float) -> str:
    if confidence >= CONFIDENCE_ACCEPT_THRESHOLD:
        return "valid"
    if confidence >= CONFIDENCE_REVIEW_THRESHOLD:
        return "review"
    return "ambiguous"


def combine_status(a: str, b: str) -> str:
    """Return whichever of two statuses is worse (valid < review < ambiguous)."""
    return a if _STATUS_SEVERITY[a] >= _STATUS_SEVERITY[b] else b


def evaluate_field(field_name: str, field: dict) -> tuple[str, list[str]]:
    """Return (status, rules_triggered) for a single BoqField."""
    status = confidence_band(field.get("confidence", 0.0))
    rules: list[str] = []
    if status == "review":
        rules.append("confidence_below_accept_threshold")
    elif status == "ambiguous":
        rules.append("confidence_below_review_threshold")

    value = field.get("value", "")

    if field_name in REQUIRED_FIELDS and not str(value).strip():
        status = combine_status(status, "ambiguous")
        rules.append("required_field_missing")

    if field_name in NUMERIC_FIELDS and str(value).strip() and parse_numeric(value) is None:
        status = combine_status(status, "ambiguous")
        rules.append("numeric_parse_failure")

    return status, rules


def evaluate_arithmetic(row: dict) -> tuple[str, list[str]] | None:
    """amount ~ quantity * rate. Returns None when quantity/rate/amount
    aren't all numeric — numeric_parse_failure already covers that case
    per-field, so arithmetic doesn't need to double-flag it."""
    quantity = parse_numeric(row["quantity"]["value"])
    rate = parse_numeric(row["rate"]["value"])
    amount = parse_numeric(row["amount"]["value"])

    if quantity is None or rate is None or amount is None:
        return None

    expected = quantity * rate
    tolerance = max(ARITHMETIC_ABSOLUTE_TOLERANCE, abs(expected) * ARITHMETIC_RELATIVE_TOLERANCE)

    if abs(amount - expected) > tolerance:
        return "ambiguous", ["arithmetic_mismatch"]

    return "valid", []
