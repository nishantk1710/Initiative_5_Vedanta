"""Canonical document evidence — the shared representation every extraction
engine's output gets normalized into before any semantic decision is made.

OCR/layout detection produces evidence. Semantic understanding (what a
region MEANS) happens later, in separate stages. This module only adds
metadata to what extraction already produced — it does not decide meaning.

`role`/`category` (line_item/metadata, table/handwriting/printed_text/...)
are the pipeline's existing PROCESSING-LANE fields — a coarse, deterministic
routing decision (does this text feed table reconstruction or metadata
regex?), not a semantic classification. They are kept as-is for backward
compatibility; `region_type` below is the physical-type counterpart and
`semantic_role` is the true semantic slot, deliberately left unset here.
"""

import itertools

# category (layout.py's coarse label) -> region_type (physical document
# region kind, independent of any routing decision made from it).
REGION_TYPE_BY_CATEGORY = {
    "table": "table",
    "handwriting": "handwriting",
    "printed_text": "text",
    "unrelated_header": "header",
    "legal_text": "footer",
    "logo": "image",
    "llm_line_item": "table",  # a row the LLM fallback identified from text
}

_counter = itertools.count(1)


def next_evidence_id() -> str:
    return f"ev_{next(_counter)}"


def to_evidence(value: dict) -> dict:
    """Enrich one already-extracted value with canonical evidence fields.
    Additive only — never removes or renames an existing key, so every
    current consumer of the flat {value, source, confidence, page, bbox,
    role, category, region_id} shape keeps working unchanged."""
    category = value.get("category")
    enriched = dict(value)
    enriched.setdefault("id", next_evidence_id())
    enriched.setdefault("normalized_value", value.get("value"))
    enriched.setdefault("region_type", REGION_TYPE_BY_CATEGORY.get(category, "unknown"))
    enriched.setdefault("semantic_role", None)
    enriched.setdefault("reading_order", None)  # filled by reading_order.py
    enriched.setdefault("language", None)
    return enriched


def attach_evidence_metadata(values: list[dict]) -> list[dict]:
    return [to_evidence(v) for v in values]
