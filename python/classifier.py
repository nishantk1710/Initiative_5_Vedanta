"""Lightweight whole-document classifier: open vocabulary, not just BOQ/invoice.

Runs ONCE per document against the combined text of all pages (not per
page) — a single mining SOW page that happens to mention a quantity looks
nothing like a stray invoice-keyword false positive when judged against the
whole document's signal counts.

Deliberately keyword/signal-count based, not LLM-based: this only has to
decide "roughly what kind of document is this" from whole-document text
already in hand, which the same fast deterministic approach used for
invoice/BOQ handles just as well for other types. Adding a new type means
adding a signal tuple below — no other document type gets special-cased
anywhere else in the deterministic engine.
"""

MIN_CONFIDENT_SIGNALS = 2

# Each entry: (type name, distinguishing keyword signals). Order doesn't
# matter — every type is scored independently and the highest-scoring
# confident type wins.
SIGNAL_SETS: dict[str, tuple[str, ...]] = {
    "invoice": (
        "tax invoice",
        "gst no",
        "hsn",
        "cgst",
        "sgst",
        "bill no",
        "amount in words",
        "details of receiver",
    ),
    "boq": (
        "scope of work",
        "bill of quantities",
        "boq",
        "excavation",
        "drilling",
        "hauling",
    ),
    "bank_statement": (
        "account statement",
        "opening balance",
        "closing balance",
        "statement of account",
        "ifsc",
        "debit",
        "credit",
        "account number",
    ),
    "resume": (
        "curriculum vitae",
        "work experience",
        "professional experience",
        "education",
        "skills",
        "objective",
        "references available",
    ),
    "contract": (
        "this agreement",
        "party of the first part",
        "hereinafter referred to as",
        "terms and conditions",
        "witnesseth",
        "governing law",
        "indemnify",
    ),
    "purchase_order": (
        "purchase order",
        "po number",
        "ship to",
        "bill to",
        "vendor",
        "delivery date",
    ),
    "receipt": (
        "cash receipt",
        "thank you for your purchase",
        "change due",
        "cashier",
        "subtotal",
    ),
}


def classify_document(page_texts: list[str]) -> dict:
    """page_texts: one combined text string per page (any source — PyMuPDF
    text or OCR'd printed text).

    Returns {"value": str, "confidence": float, "candidates": [...]}.
    "value" is "unknown" when no type reaches MIN_CONFIDENT_SIGNALS — an
    unknown document still goes through generic extraction, it just isn't
    forced into invoice/BOQ or any other type it doesn't actually match.
    "candidates" lists every type that scored at least one signal, most
    confident first, so a genuinely ambiguous document (e.g. a purchase
    order that also reads like an invoice) is representable rather than
    collapsed to a single guess.
    """
    combined = " ".join(page_texts).lower()

    scores = {
        doc_type: sum(1 for signal in signals if signal in combined)
        for doc_type, signals in SIGNAL_SETS.items()
    }

    candidates = [
        {"value": doc_type, "confidence": _confidence_for(score)}
        for doc_type, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if score > 0
    ]

    confident = [c for c in candidates if scores[c["value"]] >= MIN_CONFIDENT_SIGNALS]
    if not confident:
        return {"value": "unknown", "confidence": 0.0, "candidates": candidates}

    top_score = scores[confident[0]["value"]]
    tied = [c for c in confident if scores[c["value"]] == top_score]
    if len(tied) > 1:
        # a genuine tie between two confident types is not a confident call
        # for either — surface both as candidates rather than picking one
        # arbitrarily by dict order.
        return {"value": "unknown", "confidence": 0.0, "candidates": candidates}

    return {"value": confident[0]["value"], "confidence": confident[0]["confidence"], "candidates": candidates}


def _confidence_for(score: int) -> float:
    """Heuristic, not calibrated: more matched signals -> higher confidence,
    capped well short of 1.0 since keyword presence alone is never certain."""
    return min(0.5 + 0.15 * score, 0.95)
