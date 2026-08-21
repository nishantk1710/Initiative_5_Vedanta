"""Generic key-value field discovery for documents metadata_extractor.py's
invoice-shaped regexes don't cover.

metadata_extractor.py looks for specific invoice fields (invoice number,
GST number, grand total, ...) — there is no equivalent fixed field list for
an arbitrary document (a resume, a contract, a bank statement header).
Instead of enumerating fields per document type, this scans metadata/
leftover text lines for the general "Label: value" shape common to form
headers, contact blocks, and key-value sections, and reports back exactly
what it found.

Evidence-grounded by construction: a label that never appears in the text
never produces a key here — there is no notion of an expected field list to
pad with nulls, which is the behavior the spec explicitly rules out.
"""

import re

_LABEL_VALUE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&]{1,40}?)\s*[:\-]\s*(.+\S)\s*$")

# Labels metadata_extractor.py already extracts via dedicated, more accurate
# regex — skip them here so the two never disagree on the same field.
_SKIP_LABEL_SUBSTRINGS = ("gst", "hsn", "invoice", "bill no", "amount in words")


def _slugify(label: str) -> str:
    words = [w for w in re.split(r"[\s/&]+", label.strip().lower()) if w]
    if not words:
        return "field"
    return words[0] + "".join(w.capitalize() for w in words[1:])


def extract_generic_fields(text_lines: list[str]) -> dict:
    """Returns {field_key: {"value": str, "confidence": float, "source":
    "regex"}} for every "Label: value" line found, skipping fields
    metadata_extractor.py already owns. Confidence is a fixed, deliberately
    modest heuristic (0.6) — label/value line-splitting is a decent signal
    but this is the generic fallback path, not a validated parse; a human
    reviewing generic fields should not read this as a confident extraction."""
    fields: dict = {}
    for line in text_lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(skip in lower for skip in _SKIP_LABEL_SUBSTRINGS):
            continue

        match = _LABEL_VALUE_RE.match(stripped)
        if not match:
            continue

        label, value = match.group(1).strip(), match.group(2).strip()
        if len(label) < 2 or not value:
            continue

        key = _slugify(label)
        if key in fields:
            continue  # first occurrence wins; never overwrite with a later, possibly worse match

        fields[key] = {"value": value, "confidence": 0.6, "source": "regex"}

    return fields
