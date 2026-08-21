"""General LLM fallback for documents whose line-item table was never
detected visually.

FALLBACK PATH ONLY. line_items.py stays primary for every document where
PP-StructureV3 detects a real table region — deterministic geometry is
cheaper and more reliable when it applies. This module runs only when
layout detection found no table at all, so there is no structure to parse
geometrically and nothing smaller to reason about.

Deliberately format-agnostic: this file contains NO patterns, keywords, or
assumptions about any particular vendor, country, tax system, item-code
shape, or column layout. It passes raw text lines to the model and validates
whatever comes back against the LineItem schema. All format-specific
reasoning lives in the model, not here — which is what lets the same code
handle a POS receipt, a foreign-language invoice, or an unfamiliar layout
without modification.

Bounded-context note: Phase 6's rule is "send only ambiguous fields, never
the whole document". That rule governs the case where geometry already
produced a structure and only individual fields are unclear. Here geometry
produced NOTHING, so the failing region's own text lines are the minimum
context that can possibly work. Text from other regions and other pages is
never included.
"""

from llm_client import post_chat_json

# Fixed conservative confidence for every LLM-extracted field.
#
# Chosen over asking the model to self-assess because self-reported
# confidence is not calibrated against ground truth and skews overconfident
# — a number that looks precise while meaning little is worse than an
# honest flat signal of "less trustworthy than a direct OCR read".
#
# 0.65 specifically: it lands in rules.py's "review" band (0.60–0.84), so
# these rows read as needing a look without tipping into "ambiguous"
# (< 0.60), which would feed them straight back to the LLM normalizer and
# have the model second-guess its own output in a loop.
LLM_FIELD_CONFIDENCE = 0.65

SCHEMA_FIELDS = ("description", "quantity", "unit", "rate", "amount", "itemCode", "taxAmount")
REQUIRED_FIELDS = ("description", "amount")

_SYSTEM_PROMPT = (
    "You extract line items from the text of a single document page. The "
    "page's tabular structure could not be detected visually, so you are "
    "given the raw text lines in reading order instead.\n\n"
    "Return ONLY strict JSON, no prose and no markdown fencing, of the shape:\n"
    '{"lineItems": [{"description": "...", "amount": 0, "quantity": 0, '
    '"unit": "...", "rate": 0, "itemCode": "...", "taxAmount": 0}]}\n\n'
    "Rules:\n"
    "- Only 'description' and 'amount' are required on an item. Every other "
    "field is optional.\n"
    "- Only extract items you can clearly identify from the text. Do not "
    "guess or infer values that aren't present. Omit fields you cannot "
    "determine rather than estimating them.\n"
    "- Do not invent a unit rate when the text shows only a single figure "
    "for an item.\n"
    "- 'unit' means a unit of measurement (for example: kg, litre, metre, "
    "hour, piece, box). It is never a code or an identifier. Any product, "
    "catalogue, stock, or commodity/tax classification code belongs in "
    "'itemCode' instead — if you are unsure which of the two a value is, "
    "put it in 'itemCode' and omit 'unit'.\n"
    "- Numeric fields must be plain numbers with no currency symbols, "
    "thousands separators, or percent signs.\n"
    "- Exclude anything that is not itself a purchased/scoped line item: "
    "page headers, addresses, party details, per-item tax breakdown rows, "
    "subtotals, running totals, grand totals, summary tables, and payment "
    "or footer text.\n"
    "- If an item's tax amount is itemised on its own adjacent rows, you may "
    "sum them into that item's 'taxAmount'.\n"
    "- If the text contains no identifiable line items, return "
    '{"lineItems": []}.'
)


def _coerce_number(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            # keep the model's raw string so validator.py's
            # numeric_parse_failure can surface it rather than us silently
            # dropping a value the model did report
            return raw.strip()
    return None


def _field(value, page: int, bbox: list[float]) -> dict:
    return {
        "value": value,
        "source": "llm",
        "confidence": LLM_FIELD_CONFIDENCE,
        "page": page,
        "bbox": list(bbox),
    }


# How far from the reference position a candidate may sit before it is
# rejected in favour of the honest fallback box.
_MAX_MATCH_DISTANCE_PX = 220

# Below this length a value isn't distinctive enough for a match to be
# self-evidencing: "1" or "60" exact-matches a page number, a row index, or a
# totals line as readily as the real cell, so short matches are distance-
# gated exactly like substring matches. A long exact match (an item code, a
# specific decimal) genuinely identifies its own location and doesn't need
# the gate.
_MIN_SELF_EVIDENCING_LENGTH = 5


def _y_center(bbox: list[float]) -> float:
    return (bbox[1] + bbox[3]) / 2


def _best_matching_bbox(text: str, ocr_values: list[dict], reference_bbox: list[float]) -> list[float]:
    """Best-effort provenance: find the OCR box whose text corresponds to a
    value the model returned, so 'View source' points at the real spot on
    the page. reference_bbox anchors the search — for a row's first field
    (description) that's the parent region's bbox (no better prior exists
    yet); for every field after it, callers pass the row's own description
    bbox so amount/tax/etc. are found near where the item actually is.

    Falls back to reference_bbox itself when no sufficiently confident match
    exists — an honest approximate box beats a confidently wrong one.
    """
    needle = str(text).strip().lower()
    if not needle:
        return list(reference_bbox)

    ref_y = _y_center(reference_bbox)

    def nearest(candidates: list[dict], *, distance_gated: bool) -> list[float] | None:
        """Nearest candidate to the reference row. When distance_gated, a
        candidate too far away is discarded rather than returned."""
        if not candidates:
            return None
        best = min(candidates, key=lambda v: abs(_y_center(v["bbox"]) - ref_y))
        if distance_gated and abs(_y_center(best["bbox"]) - ref_y) > _MAX_MATCH_DISTANCE_PX:
            return None
        return list(best["bbox"])

    # A long exact match identifies itself; a short one needs the gate.
    self_evidencing = len(needle) >= _MIN_SELF_EVIDENCING_LENGTH
    exact = [v for v in ocr_values if needle == str(v["value"]).strip().lower()]
    match = nearest(exact, distance_gated=not self_evidencing)
    if match:
        return match

    contains = [v for v in ocr_values if needle in str(v["value"]).strip().lower()]
    match = nearest(contains, distance_gated=True)
    if match:
        return match

    return list(reference_bbox)


def extract_line_items_via_llm(
    text_lines: list[str],
    page_number: int,
    fallback_bbox: list[float],
    ocr_values: list[dict] | None = None,
) -> list[dict]:
    """Ask the model to identify line items in one page's text lines.

    Returns LineItem-shaped rows, every field tagged source "llm", each row
    marked so validator.py forces it to status "review". Returns [] on any
    failure — unconfigured model, transport error, malformed response, or a
    response that doesn't match the schema — never raises and never accepts
    a partially-valid response.
    """
    lines = [line.strip() for line in text_lines if line and line.strip()]
    if not lines:
        return []

    ocr_values = ocr_values or []
    user_content = "\n".join(lines)

    parsed = post_chat_json(_SYSTEM_PROMPT, user_content, log_prefix="llm-lines")
    if parsed is None:
        return []

    if not isinstance(parsed, dict) or not isinstance(parsed.get("lineItems"), list):
        print(f"[llm-lines] response missing a 'lineItems' array: {parsed!r}"[:400])
        return []

    rows: list[dict] = []
    for raw_item in parsed["lineItems"]:
        if not isinstance(raw_item, dict):
            print(f"[llm-lines] skipping non-object line item: {raw_item!r}"[:200])
            continue

        description = raw_item.get("description")
        amount = _coerce_number(raw_item.get("amount"))
        if not isinstance(description, str) or not description.strip() or amount is None:
            # required fields absent/unusable — drop this item rather than
            # fabricating a description or amount for it
            print(f"[llm-lines] skipping item missing required description/amount: {raw_item!r}"[:200])
            continue

        desc_bbox = _best_matching_bbox(description, ocr_values, fallback_bbox)
        row: dict = {
            "description": _field(description.strip(), page_number, desc_bbox),
            "amount": _field(amount, page_number, _best_matching_bbox(raw_item.get("amount"), ocr_values, desc_bbox)),
            # marker consumed (and removed) by validator.run_validation —
            # forces this row to "review" no matter how its fields score
            "_llm_extracted": True,
        }

        for name in SCHEMA_FIELDS:
            if name in REQUIRED_FIELDS or name not in raw_item:
                continue
            raw_value = raw_item[name]
            if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                continue  # omitted rather than guessed — leave the key absent

            value = _coerce_number(raw_value) if name != "unit" and name != "itemCode" else str(raw_value).strip()
            if value is None:
                continue
            row[name] = _field(value, page_number, _best_matching_bbox(raw_value, ocr_values, desc_bbox))

        rows.append(row)

    return rows
