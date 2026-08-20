import json
import os
from collections import defaultdict

from router import inspect_document
from pymupdf_parser import extract_with_pymupdf, get_page_dimensions
from layout import render_page_to_image, detect_layout, select_regions
from paddleocr_parser import extract_printed
from handwriting import extract_handwriting
from classifier import classify_document
from metadata_extractor import extract_metadata
from line_items import build_line_items
from validator import run_validation
from llm import normalize_ambiguous
from paths import document_dir


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
    all_values: list[dict] = []

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
        all_values.extend(data)

    _save_regions(document_id, regions_by_page)

    # Whole-document classification runs ONCE against every page's combined
    # text (both roles — a header's "TAX INVOICE" is a classification
    # signal even though it will never become a line item).
    texts_by_page: dict[int, list[str]] = defaultdict(list)
    for value in all_values:
        texts_by_page[value["page"]].append(str(value["value"]))
    page_texts = [" ".join(texts_by_page[p]) for p in sorted(texts_by_page)]
    document_type = classify_document(page_texts)

    # role="line_item" values only ever reach build_line_items(); role=
    # "metadata" values (header/receiver/legal/totals text) are the ONLY
    # input to extract_metadata() — the two are strictly disjoint, so a
    # text block claimed by one path can never also be misread as a line
    # item.
    line_item_values = [v for v in all_values if v.get("role") == "line_item"]
    metadata_values = [v for v in all_values if v.get("role") == "metadata"]

    line_items, leftover_metadata_texts = build_line_items(line_item_values)

    metadata_texts = [str(v["value"]) for v in metadata_values] + leftover_metadata_texts
    metadata = extract_metadata(metadata_texts, document_type)

    validated = run_validation(line_items)
    final_line_items, llm_normalized_fields = normalize_ambiguous(validated)

    total_rows = len(final_line_items)
    valid_rows = sum(1 for row in final_line_items if row["status"] == "valid")
    review_rows = sum(1 for row in final_line_items if row["status"] == "review")
    incomplete_rows = sum(1 for row in final_line_items if row["status"] == "incomplete")

    document_result = {
        "document_id": document_id,
        "document_type": document_type,
        "pages_processed": len(pages),
        "status": "completed",
        "metadata": metadata,
        "summary": {
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "review_rows": review_rows,
            "incomplete_rows": incomplete_rows,
            "llm_normalized_fields": llm_normalized_fields,
        },
        "lineItems": final_line_items,
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
