import os

import pymupdf

from paths import document_dir
from metadata_extractor import is_line_item_text

# Page render resolution: zoom 4.0 == 288 DPI. This is the ONLY place pages
# get rendered to pixels —
# detect_layout(), extract_printed(), extract_handwriting(), and the
# source-viewer crop all read this same saved PNG and the width/height
# recorded alongside it in regions.json, so every bbox already lives in this
# resolution's pixel space. Raising/lowering this constant is safe on its
# own; it only becomes a bug if some OTHER code path starts rendering pages
# at a different zoom while bboxes from this one are still in use.
RENDER_ZOOM = 4.0

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
        matrix = pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM)
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

def classify_region_label(label: str) -> str:
    return _CATEGORY_BY_LABEL.get(label, "printed_text")


def select_regions(regions: list[dict]) -> list[dict]:
    """Split detected layout regions into two disjoint roles, never both:

    - role "line_item": TABLE regions (always), plus loose PRINTED TEXT that
      looks tabular and isn't a metadata phrase, plus HANDWRITING. These are
      the only regions line_items.py ever sees.
    - role "metadata": HEADER/LEGAL TEXT regions, plus loose PRINTED TEXT
      that either doesn't look tabular or IS a metadata phrase (GST no,
      bill no, "details of receiver", totals footer, etc). These feed
      classify_document()/extract_metadata() and are never considered for
      line-item extraction.

    Only true non-text regions (LOGO: images/charts/seals — nothing to OCR)
    are dropped entirely.
    """
    kept = []
    for region in regions:
        category = classify_region_label(region["type"])

        if category == "logo":
            continue
        elif category == "table":
            kept.append({**region, "category": "table", "role": "line_item"})
        elif category == "handwriting":
            kept.append({**region, "category": "handwriting", "role": "line_item"})
        elif category == "printed_text":
            content = region.get("content", "")
            role = "line_item" if is_line_item_text(content) else "metadata"
            kept.append({**region, "category": "printed_text", "role": role})
        elif category in ("unrelated_header", "legal_text"):
            kept.append({**region, "category": category, "role": "metadata"})

    return kept
