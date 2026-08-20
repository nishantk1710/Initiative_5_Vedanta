"""Lightweight whole-document classifier: BOQ vs invoice vs unknown.

Runs ONCE per document against the combined text of all pages (not per
page) — a single mining SOW page that happens to mention a quantity looks
nothing like a stray invoice-keyword false positive when judged against the
whole document's signal counts.
"""

MIN_CONFIDENT_SIGNALS = 2

INVOICE_SIGNALS = (
    "tax invoice",
    "gst no",
    "hsn",
    "cgst",
    "sgst",
    "bill no",
    "amount in words",
    "details of receiver",
)

BOQ_SIGNALS = (
    "scope of work",
    "bill of quantities",
    "boq",
    "excavation",
    "drilling",
    "hauling",
)


def classify_document(page_texts: list[str]) -> str:
    """page_texts: one combined text string per page (any source — PyMuPDF
    text or OCR'd printed text). Returns 'boq' | 'invoice' | 'unknown'.

    Deliberately returns 'unknown' rather than guessing when neither signal
    set is confidently present — an unknown document still goes through
    generic line-item extraction, it just isn't mislabeled as boq/invoice.
    """
    combined = " ".join(page_texts).lower()

    invoice_score = sum(1 for signal in INVOICE_SIGNALS if signal in combined)
    boq_score = sum(1 for signal in BOQ_SIGNALS if signal in combined)

    if invoice_score >= MIN_CONFIDENT_SIGNALS and invoice_score > boq_score:
        return "invoice"
    if boq_score >= MIN_CONFIDENT_SIGNALS and boq_score > invoice_score:
        return "boq"
    return "unknown"
