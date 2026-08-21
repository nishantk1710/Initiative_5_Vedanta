import json
import os
from collections import defaultdict

from router import inspect_document
from pymupdf_parser import extract_with_pymupdf, get_page_dimensions
from layout import render_page_to_image, detect_layout, select_regions
from paddleocr_parser import extract_printed, ocr_full_page
from handwriting import extract_handwriting
from classifier import classify_document
from continuation import link_continuations
from generic_fields import extract_generic_fields
from generic_tables import reconstruct_physical_table
from table_semantics import classify_table_semantics
from metadata_extractor import extract_metadata
from line_items import build_line_items
from llm_line_items import extract_line_items_via_llm
from validator import run_validation
from llm import normalize_ambiguous
from paths import document_dir
from evidence import attach_evidence_metadata
from reading_order import assign_reading_order
from progress import ProgressTracker
from prescan import run_prescan

# LineItem field keys that carry an ExtractedValue — used to derive display
# regions from extracted rows.
_LINE_ITEM_FIELD_KEYS = ("itemCode", "description", "quantity", "unit", "rate", "amount", "taxRate", "taxAmount")


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


# OCR boxes whose vertical centres fall within this many pixels are treated
# as one visual line when reconstructing reading-order text for the LLM.
_LINE_Y_TOLERANCE = 14


def _group_text_lines(values: list[dict]) -> list[dict]:
    """Reassemble individual OCR boxes into reading-order text lines, so the
    LLM sees the page roughly as a person would rather than a bag of
    disconnected tokens. Purely geometric — no assumptions about content."""
    ordered = sorted(values, key=lambda v: ((v["bbox"][1] + v["bbox"][3]) / 2, v["bbox"][0]))

    lines: list[dict] = []
    for value in ordered:
        centre = (value["bbox"][1] + value["bbox"][3]) / 2
        if lines and abs(centre - lines[-1]["centre"]) <= _LINE_Y_TOLERANCE:
            lines[-1]["boxes"].append(value)
            n = len(lines[-1]["boxes"])
            lines[-1]["centre"] += (centre - lines[-1]["centre"]) / n
        else:
            lines.append({"centre": centre, "boxes": [value]})

    for line in lines:
        line["boxes"].sort(key=lambda v: v["bbox"][0])
        line["text"] = "  ".join(b["value"] for b in line["boxes"])
    return lines


def _box_center_in_bbox(box: dict, region_bbox: list[float]) -> bool:
    cx = (box["bbox"][0] + box["bbox"][2]) / 2
    cy = (box["bbox"][1] + box["bbox"][3]) / 2
    x0, y0, x1, y1 = region_bbox
    return x0 <= cx <= x1 and y0 <= cy <= y1


def _exclude_known_metadata(values: list[dict], regions: list[dict]) -> list[dict]:
    """Drop any OCR box that falls inside a region layout detection ALREADY
    classified as role=="metadata". Required to preserve Part B's disjoint-
    roles invariant ("once a text block is claimed by metadata extraction,
    it must never also be considered for line-item extraction") for the LLM
    fallback too — otherwise re-OCRing the whole page reintroduces exactly
    the header/receiver-as-line-items problem that invariant exists to
    prevent, and hands the model noise it then has to correctly ignore on
    its own."""
    metadata_bboxes = [r["bbox"] for r in regions if r.get("role") == "metadata"]
    if not metadata_bboxes:
        return values
    return [v for v in values if not any(_box_center_in_bbox(v, mb) for mb in metadata_bboxes)]


def _row_display_regions(rows: list[dict]) -> dict[int, list[dict]]:
    """Turn extracted line-item rows into per-page display regions — one box
    per row, spanning that row's fields. Used by the LLM fallback path so the
    UI shows each identified line item as its own labeled box instead of a
    single undifferentiated text block covering the page (which is all layout
    detection produced for these documents).

    Tagged category "llm_line_item" so the frontend can visually distinguish
    "found by visual table detection" from "inferred from text by the LLM" —
    an honest and useful distinction for anyone reviewing the output."""
    by_page: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        fields = [row[k] for k in _LINE_ITEM_FIELD_KEYS if k in row and row[k].get("bbox")]
        fields = [f for f in fields if any(f["bbox"])]
        if not fields:
            continue
        page = fields[0]["page"]
        bbox = [
            min(f["bbox"][0] for f in fields),
            min(f["bbox"][1] for f in fields),
            max(f["bbox"][2] for f in fields),
            max(f["bbox"][3] for f in fields),
        ]
        label = str(row.get("itemCode", row["description"])["value"])
        by_page[page].append(
            {
                "type": "llm_line_item",
                "bbox": bbox,
                "content": label,
                "category": "llm_line_item",
                "role": "line_item",
            }
        )
    return by_page


def process_document(document_id: str, file_path: str) -> dict:
    """Thin wrapper: owns the ProgressTracker lifecycle so results/<id>/
    progress.json always ends in "completed" or "error" — even if
    _process_document exits via an exception — while keeping the actual
    pipeline logic (and its stage transitions) in one place."""
    tracker = ProgressTracker(document_id)
    try:
        result = _process_document(document_id, file_path, tracker)
    except Exception as exc:  # noqa: BLE001 - surface to the caller after recording it
        tracker.fail(str(exc))
        raise
    tracker.finish()
    return result


def _process_document(document_id: str, file_path: str, tracker: ProgressTracker) -> dict:
    tracker.set_stage("loading")
    pages = inspect_document(file_path)
    tracker.set_stage("routing")
    tracker.init_pages(pages)

    regions_by_page: list[dict] = []
    all_values: list[dict] = []
    image_path_by_page: dict[int, str] = {}
    render_dims_by_page: dict[int, tuple[int, int]] = {}
    any_scanned = any(page["type"] == "scanned" for page in pages)

    tracker.set_stage("rendering")
    # Rendering + pre-scan genuinely run one page at a time — set_page_stage
    # reports exactly that, so a client polling mid-render sees which page
    # is actually being worked on right now, not every page "active" at once.
    for page in pages:
        page_number = page["page"]
        tracker.set_page_stage(page_number, "prescan", "running")
        # rendered for every page regardless of routing — display only,
        # never fed into extraction/OCR for digital pages
        _image_path, render_width, render_height = render_page_to_image(
            file_path, page_number, document_id
        )
        image_path_by_page[page_number] = _image_path
        render_dims_by_page[page_number] = (render_width, render_height)

    # Pre-scan quality gate: runs on every rendered page BEFORE layout
    # detection/OCR even starts, so a poor scan is flagged up front rather
    # than discovered only after the user has waited through the full
    # (60-90s/page) OCR pipeline. A "fail" page is still processed in full —
    # this only annotates the result, never blocks extraction.
    tracker.set_stage("prescan")
    prescan_results = []
    for page in pages:
        page_number = page["page"]
        prescan_results.append(run_prescan(image_path_by_page[page_number], page_number))
        tracker.set_page_stage(page_number, "prescan", "done")

    layout_stage_entered = False
    for page in pages:
        page_number = page["page"]
        _image_path = image_path_by_page[page_number]
        render_width, render_height = render_dims_by_page[page_number]
        tracker.set_page_stage(page_number, "ocr", "running")

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
            if not layout_stage_entered:
                # First scanned page in the document — this is genuinely
                # where layout detection/OCR work begins, so the stage
                # transition happens here rather than being pre-announced
                # before any scanned page was even reached.
                tracker.set_stage("layout_detection")
                layout_stage_entered = True

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
        tracker.set_page_stage(page_number, "ocr", "done")

    if any_scanned:
        tracker.set_stage("ocr")
        tracker.set_stage("handwriting_ocr")

    _save_regions(document_id, regions_by_page)

    # Canonical evidence: additive metadata only (id, normalized_value,
    # region_type, semantic_role, reading_order, language). Existing
    # role/category keys are untouched, so every downstream consumer that
    # only knows about those keeps working unchanged.
    all_values = attach_evidence_metadata(all_values)

    # Reading order is computed on the actual evidence (all_values), grouped
    # by page, not on regions_by_page's display-oriented "regions" list —
    # for scanned pages those are layout REGIONS (pre-OCR, one per detected
    # block), a different granularity than the per-token/line evidence here.
    values_by_page: dict[int, list[dict]] = defaultdict(list)
    for value in all_values:
        values_by_page[value["page"]].append(value)
    for page_values in values_by_page.values():
        assign_reading_order(page_values)

    tracker.set_stage("document_understanding")
    # document_understanding/schema_discovery/semantic_extraction genuinely
    # run once over EVERY page's evidence together (classification, table
    # reconstruction, metadata extraction all operate on all_values as a
    # whole) — marking every page's "structure" group running/done here is
    # an honest reflection of that, not a faked simultaneity.
    tracker.set_stage_group_for_all_pages("structure", "running")

    # Whole-document classification runs ONCE against every page's combined
    # text (both roles — a header's "TAX INVOICE" is a classification
    # signal even though it will never become a line item).
    texts_by_page: dict[int, list[str]] = defaultdict(list)
    for value in all_values:
        texts_by_page[value["page"]].append(str(value["value"]))
    page_texts = [" ".join(texts_by_page[p]) for p in sorted(texts_by_page)]
    classification = classify_document(page_texts)
    document_type = classification["value"]

    # role="line_item" values only ever reach build_line_items(); role=
    # "metadata" values (header/receiver/legal/totals text) are the ONLY
    # input to extract_metadata() — the two are strictly disjoint, so a
    # text block claimed by one path can never also be misread as a line
    # item.
    line_item_values = [v for v in all_values if v.get("role") == "line_item"]
    metadata_values = [v for v in all_values if v.get("role") == "metadata"]

    tracker.set_stage("schema_discovery")

    line_items, leftover_metadata_texts, non_line_item_tables = build_line_items(line_item_values)

    # Tables whose header didn't match any known BOQ/invoice column keyword
    # aren't necessarily unstructured — they might be a bank statement's
    # transaction table, an attendance sheet, etc. Give them a generic
    # physical reconstruction and a best-guess (possibly "unknown") semantic
    # role, rather than only ever routing their text into metadata.
    generic_tables: list[dict] = []
    for region_id, region_values in non_line_item_tables.items():
        physical = reconstruct_physical_table(region_id, region_values)
        if physical is None or physical["row_count"] == 0:
            continue
        semantic = classify_table_semantics(physical["headers"])
        physical["semantic_role"] = semantic["value"]
        physical["semantic_confidence"] = semantic["confidence"]
        generic_tables.append(physical)

    # A table split across a page break reconstructs as two independent
    # fragments (the next page's continuation usually has no header row of
    # its own) — link them from real bbox/column geometry into one logical
    # table with pages=[p1,p2,...], rather than leaving the frontend to
    # guess whether two tables are related.
    page_heights = {p: dims[1] for p, dims in render_dims_by_page.items()}
    page_widths = {p: dims[0] for p, dims in render_dims_by_page.items()}
    generic_tables = link_continuations(generic_tables, page_heights, page_widths)

    # --- FALLBACK: geometry found no trustworthy structure -------------
    # Two distinct ways geometry can fail to produce real line items, and
    # neither is reliably signaled by "did PP-StructureV3 label a region
    # 'table'": (1) it labels NO region a table at all — e.g. a borderless
    # POS receipt with no cell grid; (2) it DOES label a region a table, but
    # line_items.py's header-keyword matching (English column names:
    # "description"/"qty"/"rate"/...) finds none of them, because the
    # document's headers are in another language — that table's rows then
    # get silently discarded as leftover_metadata_texts rather than becoming
    # line items. Gating on "was a table region detected" would miss case
    # (2) entirely, so the real condition is "did the primary path produce
    # trustworthy rows at all" — checked directly below, not inferred from a
    # layout-detection label.
    #
    # A non-empty line_items list isn't proof of real structure either: when
    # no header row could be matched, the loose-text path still emits one
    # row per visual line via blind left-to-right position guessing, tagged
    # "_position_guessed". If EVERY row came from that guess, there's
    # genuinely no detected structure — same situation as an empty list.
    #
    # When this fires, the model gets that page's own text (minus anything
    # already claimed by a known metadata region) and identifies the line
    # items itself — format-specific reasoning lives entirely in the model,
    # not here. Scoped to the failing page's text only, never other pages.
    only_guessed_rows = bool(line_items) and all(row.get("_position_guessed") for row in line_items)
    used_llm_fallback = False
    if not line_items or only_guessed_rows:
        fallback_rows: list[dict] = []
        for entry in regions_by_page:
            image_path = image_path_by_page.get(entry["page"])
            if entry["type"] != "scanned" or not image_path:
                continue

            page_values = ocr_full_page(image_path, entry["page"])
            if not page_values:
                continue
            # exclude text already claimed by a known metadata region (e.g.
            # the header/receiver block PP-StructureV3 DID detect, even
            # though it found no table) before this ever reaches the model
            page_values = _exclude_known_metadata(page_values, entry["regions"])
            if not page_values:
                continue

            page_bbox = [0.0, 0.0, float(entry["width"]), float(entry["height"])]
            text_lines = [
                line["text"]
                for line in _group_text_lines(page_values)
            ]
            fallback_rows.extend(
                extract_line_items_via_llm(
                    text_lines, entry["page"], page_bbox, ocr_values=page_values
                )
            )

        if fallback_rows:
            line_items = fallback_rows
            used_llm_fallback = True
            # Replace the single undifferentiated text region with one box
            # per identified line item, so region overlays and per-row
            # "View source" are meaningful.
            row_regions = _row_display_regions(fallback_rows)
            for entry in regions_by_page:
                if entry["page"] in row_regions:
                    entry["regions"] = [
                        r for r in entry["regions"] if r.get("role") == "metadata"
                    ] + row_regions[entry["page"]]
            _save_regions(document_id, regions_by_page)

    tracker.set_stage("semantic_extraction")

    metadata_texts = [str(v["value"]) for v in metadata_values] + leftover_metadata_texts
    metadata = extract_metadata(metadata_texts, document_type)

    # Generic key-value discovery runs on the SAME metadata text regardless
    # of document_type — it has no fixed field list, so it never pads a
    # non-invoice document with invoice-shaped nulls, and never conflicts
    # with metadata's dedicated invoice regex (generic_fields.py skips those
    # labels outright).
    generic_fields = extract_generic_fields(metadata_texts)

    tracker.set_stage_group_for_all_pages("structure", "done")
    tracker.set_stage("validation")
    # validation/finalization also genuinely run once over every row in a
    # single pass (run_validation/normalize_ambiguous), not page by page.
    tracker.set_stage_group_for_all_pages("decide", "running")

    validated = run_validation(line_items)
    final_line_items, llm_normalized_fields = normalize_ambiguous(validated)

    tracker.set_stage("finalization")
    tracker.set_stage_group_for_all_pages("decide", "done")

    total_rows = len(final_line_items)
    valid_rows = sum(1 for row in final_line_items if row["status"] == "valid")
    review_rows = sum(1 for row in final_line_items if row["status"] == "review")
    incomplete_rows = sum(1 for row in final_line_items if row["status"] == "incomplete")

    document_result = {
        "document_id": document_id,
        "document_type": document_type,
        "document_type_confidence": classification["confidence"],
        "document_type_candidates": classification["candidates"],
        "tables": generic_tables,
        "fields": generic_fields,
        "prescan": prescan_results,
        "pages_processed": len(pages),
        "status": "completed",
        "metadata": metadata,
        "extraction_path": "llm_text_fallback" if used_llm_fallback else "table_regions",
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
