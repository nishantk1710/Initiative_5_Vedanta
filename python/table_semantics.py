"""Deciding what a physically-reconstructed table MEANS, layered on top of
generic_tables.py's shape-only reconstruction.

A table is not automatically a line-item table. This module gives a cheap,
deterministic first guess at a table's semantic role from its header text
alone — the same keyword-signal-counting approach classifier.py uses for
whole documents, applied at table granularity. A role is only assigned when
confidently signaled; anything else stays "unknown" rather than being forced
into a role it may not have (a bank statement's transaction table must never
be mislabeled "invoice_items" just because both have an "amount"-like
column). Ambiguous or unmatched tables are exactly where a later LLM-backed
interpreter is expected to take over — this module never guesses past its
own confidence.
"""

MIN_HEADER_MATCHES = 2

SEMANTIC_SIGNAL_SETS: dict[str, tuple[str, ...]] = {
    "invoice_items": ("description", "qty", "quantity", "rate", "amount", "particulars", "hsn"),
    "bank_transactions": ("date", "description", "debit", "credit", "balance", "narration"),
    "attendance": ("employee", "in time", "out time", "present", "absent", "leave"),
    "inventory": ("sku", "stock", "warehouse", "reorder", "on hand"),
}


def classify_table_semantics(headers: list[str]) -> dict:
    """Returns {"value": str, "confidence": float}. "unknown" (confidence
    0.0) when no role's signal set is confidently present in the header
    row — never picks a role just because it scored highest if that score
    is still too low to trust."""
    combined = " ".join(h.lower() for h in headers)

    scores = {
        role: sum(1 for signal in signals if signal in combined) for role, signals in SEMANTIC_SIGNAL_SETS.items()
    }

    best_role = max(scores, key=scores.get) if scores else None
    best_score = scores.get(best_role, 0)
    if best_role is None or best_score < MIN_HEADER_MATCHES:
        return {"value": "unknown", "confidence": 0.0}

    return {"value": best_role, "confidence": min(0.5 + 0.15 * best_score, 0.95)}
