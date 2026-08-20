"""Document-level metadata extraction (vendor/invoice-number/date/buyer/totals)
and the shared "is this text a line item or metadata" classification used by
both the digital (PyMuPDF) and scanned (PP-StructureV3 printed-text) paths.

Intentionally lightweight line-based pattern matching — not a general NER
system. Good enough to pull the obvious fields off a typical invoice header/
footer; anything it misses just leaves that DocumentMetadata field absent.
"""

import re

# Phrase-level signals that mark a text line as document metadata (header/
# receiver/footer boilerplate) rather than a line-item candidate, even when
# it contains digits or currency-looking numbers (e.g. a GST number or bill
# date) that would otherwise pass the old "has digits" line-item heuristic.
_METADATA_PHRASE_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"tax\s*invoice",
        r"gst\s*no",
        r"bill\s*no",
        r"invoice\s*(no|number|date)",
        r"amount\s*in\s*words",
        r"details?\s*of\s*receiver",
        r"place\s*of\s*supply",
        r"state\s*name",
        r"pan\s*no",
        r"terms?\s*(and|&)\s*conditions?",
        r"declaration",
        r"authoriz(ed|ation)\s*signat",
        r"bank\s*details",
        r"\bifsc\b",
        r"\bcgst\b",
        r"\bsgst\b",
        r"\bigst\b",
        r"taxable\s*value",
        r"grand\s*total",
        r"total\s*amount",
        r"net\s*amount",
    )
]


def is_metadata_line(text: str) -> bool:
    """True if this text line/block is document metadata (header, receiver
    details, legal boilerplate, totals footer) and must never be treated as
    a line-item candidate — regardless of whether it also contains digits.
    """
    return any(p.search(text) for p in _METADATA_PHRASE_PATTERNS)


_LINE_ITEM_KEYWORDS = (
    "description",
    "qty",
    "quantity",
    "unit",
    "rate",
    "amount",
    "item",
    "bill of quantities",
    "boq",
    "total",
    "hsn",
)


def is_line_item_text(text: str) -> bool:
    """Shared "does this loose text line look like a line item?" heuristic,
    used for both digital (PyMuPDF span) and scanned (printed_text region)
    text that isn't already inside a detected table region. A metadata
    phrase (GST no, bill no, ...) is excluded even if it contains digits —
    digit-presence alone is not sufficient once invoices are in scope."""
    if not text:
        return False
    if is_metadata_line(text):
        return False
    if any(ch.isdigit() for ch in text):
        return True
    lower = text.lower()
    return any(keyword in lower for keyword in _LINE_ITEM_KEYWORDS)


_INVOICE_NUMBER_RE = re.compile(r"bill\s*no\.?\s*[:\-]?\s*([A-Za-z0-9\-/]+)", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
_GST_NO_RE = re.compile(r"gst\s*no\.?\s*[:\-]?\s*([0-9A-Z]{10,15})", re.I)
_BUYER_NAME_RE = re.compile(r"name\s*[:\-]\s*(.+)", re.I)

_SUBTOTAL_RE = re.compile(r"\b(?:sub\s*total|taxable\s*value)\b[^\d]*([\d,]+\.?\d*)", re.I)
# CGST/SGST/IGST usually appear on separate lines and must be SUMMED, not
# overwritten — a line matching this contributes to the running tax total.
_TAX_COMPONENT_RE = re.compile(r"\b(?:cgst|sgst|igst|total\s*tax|gst\s*amount)\b[^\d]*([\d,]+\.?\d*)", re.I)
_GRAND_TOTAL_RE = re.compile(r"\b(?:grand\s*total|total\s*amount|net\s*amount)\b[^\d]*([\d,]+\.?\d*)", re.I)

_RECEIVER_HEADING_RE = re.compile(r"details?\s*of\s*receiver", re.I)
_VENDOR_STOPWORDS_RE = re.compile(
    r"tax\s*invoice|gst\s*no|bill\s*no|invoice|date|amount\s*in\s*words", re.I
)


def _parse_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def extract_metadata(metadata_lines: list[str], document_type: str) -> dict:
    """Scan the text lines routed to the 'metadata' role (header/receiver/
    legal/totals text — never the ones that became line items) for the
    obvious DocumentMetadata fields."""
    meta: dict = {"documentType": document_type}
    totals: dict = {}

    seen_receiver_heading = False
    vendor_candidate: str | None = None

    for line in metadata_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if _RECEIVER_HEADING_RE.search(stripped):
            seen_receiver_heading = True
            continue

        if "invoiceNumber" not in meta:
            m = _INVOICE_NUMBER_RE.search(stripped)
            if m:
                meta["invoiceNumber"] = m.group(1)

        if "date" not in meta:
            m = _DATE_RE.search(stripped)
            if m:
                meta["date"] = m.group(1)

        if "vendor" not in meta:
            m = _GST_NO_RE.search(stripped)
            if m:
                meta["vendor"] = vendor_candidate or stripped

        if not seen_receiver_heading and "buyer" not in meta:
            m = _BUYER_NAME_RE.search(stripped)
            if m:
                meta["buyer"] = m.group(1).strip()

        if seen_receiver_heading and "buyer" not in meta:
            m = _BUYER_NAME_RE.search(stripped)
            if m:
                meta["buyer"] = m.group(1).strip()

        # crude vendor guess: first plain-text line (no digits, no known
        # pattern) seen before the receiver heading — usually the letterhead
        if (
            vendor_candidate is None
            and not seen_receiver_heading
            and not any(ch.isdigit() for ch in stripped)
            and not _VENDOR_STOPWORDS_RE.search(stripped)
            and len(stripped) > 2
        ):
            vendor_candidate = stripped

        if "subtotal" not in totals:
            m = _SUBTOTAL_RE.search(stripped)
            if m:
                value = _parse_number(m.group(1))
                if value is not None:
                    totals["subtotal"] = value

        m = _TAX_COMPONENT_RE.search(stripped)
        if m:
            value = _parse_number(m.group(1))
            if value is not None:
                totals["tax"] = totals.get("tax", 0.0) + value

        if "grandTotal" not in totals:
            m = _GRAND_TOTAL_RE.search(stripped)
            if m:
                value = _parse_number(m.group(1))
                if value is not None:
                    totals["grandTotal"] = value

    if "vendor" not in meta and vendor_candidate:
        meta["vendor"] = vendor_candidate

    if totals:
        meta["totals"] = totals

    return meta
