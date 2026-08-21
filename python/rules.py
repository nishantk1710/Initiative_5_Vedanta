"""Deterministic validation rules for BOQ rows/fields.

NOTE: the confidence bands and arithmetic tolerance below are a starting
point, not calibrated against real mining SOWs — only against the three
bundled dummy samples. Re-tune these constants once real documents are
available.
"""

NUMERIC_FIELDS = ("quantity", "rate", "amount", "taxRate", "taxAmount")
# "unit" is optional on LineItem (often absent on invoices) — never required.
REQUIRED_FIELDS = ("description", "quantity", "rate", "amount")

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
    """Return (status, rules_triggered) for a single BoqField.

    A field with no value at all (build_boq found nothing for this column in
    this row) is a DIFFERENT situation from a field that was extracted but
    scored low confidence — the former was never "attempted" and must not be
    judged by confidence_band(0.0), or every genuinely-empty non-required
    column would read as "ambiguous garbage" and drag down row-level
    aggregates. Only a missing REQUIRED field is actually a problem here.
    """
    value = field.get("value", "")
    has_value = bool(str(value).strip())

    if not has_value:
        if field_name in REQUIRED_FIELDS:
            return "ambiguous", ["required_field_missing"]
        return "valid", []

    status = confidence_band(field.get("confidence", 0.0))
    rules: list[str] = []
    if status == "review":
        rules.append("confidence_below_accept_threshold")
    elif status == "ambiguous":
        rules.append("confidence_below_review_threshold")

    if field_name in NUMERIC_FIELDS and parse_numeric(value) is None:
        status = combine_status(status, "ambiguous")
        rules.append("numeric_parse_failure")

    return status, rules


def _within_tolerance(amount: float, expected: float) -> bool:
    tolerance = max(ARITHMETIC_ABSOLUTE_TOLERANCE, abs(expected) * ARITHMETIC_RELATIVE_TOLERANCE)
    return abs(amount - expected) <= tolerance


def evaluate_arithmetic(row: dict) -> tuple[str, list[str], str | None] | None:
    """amount ~ quantity * rate, tolerant of tax-inclusive invoice amounts:
    if the plain check fails but a taxAmount field is present and
    quantity*rate + taxAmount ~ amount, that's still valid — not every
    invoice line's "amount" is pre-tax.

    Returns None (no verdict) whenever quantity/rate/amount aren't all
    present and numeric — quantity and rate are optional on LineItem, and a
    row that never reported a unit rate has no arithmetic to check rather
    than a failed check.

    On a mismatch, the third element names the SUSPECT field — the lowest-
    confidence of quantity/rate/amount — rather than unconditionally
    `amount`. This is a deterministic first-pass guess, cheap and immediate
    (no LLM needed): the three correlated fields came from the same OCR
    pass, so the one the engine itself was least sure about is the more
    likely misread, and the equation gives no independent evidence pointing
    at any specific one of the three. Blaming `amount` regardless of which
    field actually scored lowest is what let a misread quantity (1.1 -> 11)
    get "corrected" by rewriting an already-correct amount (19800 -> 198000)
    — verified live on a real document. correction.py's LLM-backed proposal
    step still runs on top of this guess and is subject to its own
    acceptance gate; this only fixes where the rule attaches, not whether a
    value ever actually gets mutated.
    """
    quantity_field = row.get("quantity")
    rate_field = row.get("rate")
    amount_field = row.get("amount")
    if quantity_field is None or rate_field is None or amount_field is None:
        return None

    quantity = parse_numeric(quantity_field["value"])
    rate = parse_numeric(rate_field["value"])
    amount = parse_numeric(amount_field["value"])

    if quantity is None or rate is None or amount is None:
        return None

    expected = quantity * rate
    if _within_tolerance(amount, expected):
        return "valid", [], None

    tax_field = row.get("taxAmount")
    if tax_field is not None:
        tax_amount = parse_numeric(tax_field["value"])
        if tax_amount is not None and _within_tolerance(amount, expected + tax_amount):
            return "valid", [], None

    suspect_field = min(
        ("quantity", "rate", "amount"),
        key=lambda name: row[name].get("confidence", 0.0),
    )
    return "ambiguous", ["arithmetic_mismatch"], suspect_field
