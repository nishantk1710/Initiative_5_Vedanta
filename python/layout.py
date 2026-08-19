import os

import pymupdf

from paths import document_dir

RENDER_DPI = 200

INSTALL_HINT = (
    'pip install paddlepaddle paddleocr --break-system-packages\n'
    '    pip install "paddlex[ocr]==<paddlex-version>" --break-system-packages '
    "(paddleocr's PP-StructureV3 needs this extra; <paddlex-version> must match "
    "`pip show paddlex`)\n\n"
    "(On Windows/venv --break-system-packages is unnecessary and harmless to "
    "omit; it only matters on Debian/Ubuntu-managed Python where pip refuses "
    "installs outside a venv by default.)"
)

_structure_engine = None
_structure_import_error: Exception | None = None
_structure_runtime_error: Exception | None = None

try:
    from paddleocr import PPStructureV3

    _PPSTRUCTURE_AVAILABLE = True
except ImportError as exc:  # PP-StructureV3 not installed in this environment
    _PPSTRUCTURE_AVAILABLE = False
    _structure_import_error = exc


def render_page_to_image(file_path: str, page_number: int, document_id: str) -> tuple[str, int, int]:
    """Render a single page (1-indexed) of a PDF to a PNG file. Called for
    EVERY page regardless of routing — digital pages still get their text
    pulled via PyMuPDF only (never OCR'd); the rendered image here is purely
    so the frontend can display the document. Only the requested page is
    rendered, never the whole document. Returns (image_path, width, height)
    in the rendered PNG's pixel dimensions."""
    pages_dir = os.path.join(document_dir(document_id), "pages")
    os.makedirs(pages_dir, exist_ok=True)

    image_path = os.path.join(pages_dir, f"page_{page_number:03d}.png")

    with pymupdf.open(file_path) as doc:
        page = doc[page_number - 1]
        zoom = RENDER_DPI / 72
        matrix = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        pix.save(image_path)
        width, height = pix.width, pix.height

    return image_path, width, height


def _get_structure_engine():
    global _structure_engine
    if _structure_engine is None:
        _structure_engine = PPStructureV3(device="cpu")
    return _structure_engine


def warm_up() -> None:
    """Construct the PP-StructureV3 engine now instead of lazily on the
    first request. Building its ~13 sub-models is CPU-bound and can take
    well over a minute the first time — paying that cost during server
    startup (visible in the uvicorn log) avoids the first real /process
    call timing out."""
    if _PPSTRUCTURE_AVAILABLE:
        _get_structure_engine()


def _mock_detect_layout(image_path: str, page_number: int, reason: str) -> dict:
    """Clearly-labeled placeholder used when PP-StructureV3 can't produce a
    real result in this environment (not installed, or installed but broken
    at inference time — see `reason`). Install/repair with:

        {install_hint}
    """.format(install_hint=INSTALL_HINT)
    return {
        "page": page_number,
        "regions": [
            {
                "type": "mock",
                "bbox": [0, 0, 0, 0],
                "note": f"PP-StructureV3 result unavailable — this is a stub. Reason: {reason}",
            }
        ],
    }


def detect_layout(image_path: str, page_number: int) -> dict:
    """Run PP-StructureV3 on a rendered page image and return detected
    regions (text/table/image/etc.) with bounding boxes."""
    if not _PPSTRUCTURE_AVAILABLE:
        return _mock_detect_layout(image_path, page_number, reason=str(_structure_import_error))

    try:
        engine = _get_structure_engine()
        output = engine.predict(image_path)
    except Exception as exc:  # noqa: BLE001 - PP-StructureV3 installed but failing at inference
        global _structure_runtime_error
        _structure_runtime_error = exc
        return _mock_detect_layout(image_path, page_number, reason=str(exc))

    regions = []
    for result in output:
        blocks = result.get("parsing_res_list") or []
        for block in blocks:
            block_type = getattr(block, "label", "unknown")
            bbox = list(getattr(block, "bbox", [0, 0, 0, 0]))
            content = getattr(block, "content", "") or ""
            regions.append({"type": block_type, "bbox": bbox, "content": content})

    return {"page": page_number, "regions": regions}


# --- Region selection -------------------------------------------------
#
# PP-StructureV3 / PP-DocLayout label -> coarse category used for the
# keep/drop policy. Labels not seen in practice default to "printed_text"
# so the BOQ-keyword heuristic gets a chance rather than silently dropping
# unfamiliar layout types.
_CATEGORY_BY_LABEL = {
    "table": "table",
    "text": "printed_text",
    "paragraph_title": "printed_text",
    "doc_title": "printed_text",
    "table_title": "printed_text",
    "content": "printed_text",
    "abstract": "printed_text",
    "aside_text": "printed_text",
    "reference_content": "printed_text",
    "handwriting": "handwriting",
    "handwriting_text": "handwriting",
    "image": "logo",
    "logo": "logo",
    "chart": "logo",
    "seal": "logo",
    "header": "unrelated_header",
    "footer": "unrelated_header",
    "figure_title": "unrelated_header",
    "footnote": "legal_text",
    "reference": "legal_text",
    "algorithm": "legal_text",
    "formula": "legal_text",
    "formula_number": "legal_text",
}

_BOQ_KEYWORDS = (
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
)


def classify_region_label(label: str) -> str:
    return _CATEGORY_BY_LABEL.get(label, "printed_text")


def _is_boq_related(text: str) -> bool:
    if not text:
        return False
    if any(ch.isdigit() for ch in text):
        return True
    lower = text.lower()
    return any(keyword in lower for keyword in _BOQ_KEYWORDS)


def select_regions(regions: list[dict]) -> list[dict]:
    """Apply the keep/drop policy over detected layout regions:
    TABLE -> keep, PRINTED TEXT -> keep only if BOQ-related (has digits or a
    BOQ keyword), HANDWRITING -> keep, LOGO/LEGAL TEXT/UNRELATED HEADER ->
    drop. Kept regions are tagged with a `category` field consumed by the
    OCR/handwriting extractors."""
    kept = []
    for region in regions:
        category = classify_region_label(region["type"])

        if category == "table":
            kept.append({**region, "category": "table"})
        elif category == "printed_text":
            if _is_boq_related(region.get("content", "")):
                kept.append({**region, "category": "printed_text"})
        elif category == "handwriting":
            kept.append({**region, "category": "handwriting"})
        # "logo", "legal_text", "unrelated_header" -> dropped

    return kept
