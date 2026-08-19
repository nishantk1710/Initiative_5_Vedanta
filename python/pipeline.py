import json
import os

from router import inspect_document
from pymupdf_parser import extract_with_pymupdf, get_page_dimensions
from layout import render_page_to_image, detect_layout, select_regions
from paddleocr_parser import extract_printed
from handwriting import extract_handwriting
from boq import build_boq
from validator import run_validation
from llm import normalize_ambiguous
from paths import document_dir

DOCUMENT_TYPE = "mining_sow"


def merge(printed: list[dict], handwritten: list[dict]) -> list[dict]:
    """Combine printed (PaddleOCR) and handwritten (Tesseract) extractions
    for a scanned page into one list. Both are already normalized to the
    shared ExtractedValue shape ({value, source, confidence, page, bbox}),
    so callers never need to know which engine produced which field."""
    return printed + handwritten


def prepare_document(document_id: str, file_path: str) -> dict:
    """Cheap pre-pass used right after upload, before the user clicks
    'Process SOW': runs only the router (no layout/OCR) and renders every
    page to PNG so the frontend can show a real thumbnail and know the
    digital/scanned split immediately, without waiting for the full
    pipeline."""
    pages = inspect_document(file_path)
    for page in pages:
        render_page_to_image(file_path, page["page"], document_id)
    return {"document_id": document_id, "pages": pages}


def process_document(document_id: str, file_path: str) -> dict:
    pages = inspect_document(file_path)

    regions_by_page: list[dict] = []
    result: list[dict] = []

    for page in pages:
        page_number = page["page"]
        # rendered for every page regardless of routing — display only,
        # never fed into extraction/OCR for digital pages
        _image_path, render_width, render_height = render_page_to_image(
            file_path, page_number, document_id
        )

        if page["type"] == "digital":
            data = extract_with_pymupdf(page, file_path)
            page_width, page_height = get_page_dimensions(file_path, page_number)
            regions_by_page.append(
                {
                    "page": page_number,
                    "type": "digital",
                    "width": page_width,
                    "height": page_height,
                    "regions": data,
                }
            )
        else:
            layout = detect_layout(_image_path, page_number)
            layout["regions"] = select_regions(layout["regions"])

            printed = extract_printed(layout, _image_path, document_id)
            handwritten = extract_handwriting(layout, _image_path, document_id)
            data = merge(printed, handwritten)

            regions_by_page.append(
                {
                    "page": page_number,
                    "type": "scanned",
                    "width": render_width,
                    "height": render_height,
                    "regions": layout["regions"],
                }
            )
        result.extend(data)

    _save_regions(document_id, regions_by_page)

    boq = build_boq(result)
    validated = run_validation(boq)
    final_boq, llm_normalized_fields = normalize_ambiguous(validated)

    total_rows = len(final_boq)
    valid_rows = sum(1 for row in final_boq if row["status"] == "valid")
    review_rows = sum(1 for row in final_boq if row["status"] == "review")

    document_result = {
        "document_id": document_id,
        "document_type": DOCUMENT_TYPE,
        "pages_processed": len(pages),
        "status": "completed",
        "summary": {
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "review_rows": review_rows,
            "llm_normalized_fields": llm_normalized_fields,
        },
        "boq": final_boq,
    }

    _save_result(document_id, document_result)

    return document_result


def _save_regions(document_id: str, regions_by_page: list[dict]) -> None:
    out_dir = document_dir(document_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "regions.json"), "w", encoding="utf-8") as f:
        json.dump(regions_by_page, f, indent=2)


def _save_result(document_id: str, document_result: dict) -> None:
    out_dir = document_dir(document_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(document_result, f, indent=2)
