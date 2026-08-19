import re
import string

import pymupdf

MIN_MEANINGFUL_CHARS = 40
MIN_PRINTABLE_RATIO = 0.85
MIN_ALPHANUMERIC_RATIO = 0.4
MAX_REPEATED_CHAR_RUN = 20

_PRINTABLE = set(string.printable)


def is_meaningful_text(text: str) -> bool:
    """Decide whether extracted page text plausibly represents real body text,
    as opposed to whitespace, OCR noise, or stray metadata-like strings PyMuPDF
    sometimes pulls off scanned/image-only pages (headers, watermarks, page
    numbers embedded as a text layer, etc.)."""
    if not text:
        return False

    stripped = text.strip()
    if len(stripped) < MIN_MEANINGFUL_CHARS:
        return False

    printable_count = sum(1 for ch in stripped if ch in _PRINTABLE)
    if printable_count / len(stripped) < MIN_PRINTABLE_RATIO:
        return False

    alnum_count = sum(1 for ch in stripped if ch.isalnum())
    if alnum_count / len(stripped) < MIN_ALPHANUMERIC_RATIO:
        return False

    # Reject strings dominated by a single repeated character (e.g. "....." or
    # a run of underscores from a form template), even if long enough overall.
    longest_run = 1
    current_run = 1
    for prev, curr in zip(stripped, stripped[1:]):
        if curr == prev:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 1
    if longest_run >= MAX_REPEATED_CHAR_RUN:
        return False

    # Reject text with no real words (e.g. isolated punctuation/digits with
    # no alphabetic runs of reasonable length).
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    if len(words) < 3:
        return False

    return True


def inspect_document(file_path: str) -> list[dict]:
    """Open a PDF and classify each page as 'digital' (has a real extractable
    text layer) or 'scanned' (image-only / no meaningful text layer)."""
    results = []
    with pymupdf.open(file_path) as doc:
        for index, page in enumerate(doc):
            text = page.get_text()
            page_type = "digital" if is_meaningful_text(text) else "scanned"
            results.append({"page": index + 1, "type": page_type})
    return results
