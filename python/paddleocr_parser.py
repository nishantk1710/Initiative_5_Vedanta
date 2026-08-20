import os

import cv2

from paddleocr import PaddleOCR
from paths import document_dir

_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
            device="cpu",
        )
    return _ocr_engine


def warm_up() -> None:
    """Construct the PaddleOCR engine now instead of lazily on first use —
    same rationale as layout.warm_up()."""
    _get_ocr_engine()


def extract_printed(layout: dict, image_path: str, document_id: str) -> list[dict]:
    """Crop every kept non-handwriting region from the rendered page image
    (table, printed_text, unrelated_header, legal_text — i.e. every text-
    bearing region select_regions() didn't drop as pure logo/image), run
    PaddleOCR on each crop, and return one ExtractedValue-shaped dict per
    detected text element, tagged with the region's `role` ("line_item" or
    "metadata") and `category` so callers can route header/receiver/totals
    text to metadata extraction while keeping it out of line-item building.
    Crops are saved under results/<document_id>/regions/ for provenance."""
    page_number = layout["page"]
    regions = [r for r in layout["regions"] if r.get("category") != "handwriting"]
    if not regions:
        return []

    crops_dir = os.path.join(document_dir(document_id), "regions")
    os.makedirs(crops_dir, exist_ok=True)

    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Could not read rendered page image: {image_path}")

    engine = _get_ocr_engine()
    values: list[dict] = []

    for region_index, region in enumerate(regions):
        x0, y0, x1, y1 = [int(round(v)) for v in region["bbox"]]
        crop = image[max(y0, 0) : y1, max(x0, 0) : x1]
        if crop.size == 0:
            continue

        crop_path = os.path.join(
            crops_dir, f"page_{page_number:03d}_{region['category']}_{region_index}.png"
        )
        cv2.imwrite(crop_path, crop)

        results = engine.predict(crop_path)
        for result in results:
            texts = result.get("rec_texts") or []
            scores = result.get("rec_scores") or []
            boxes = result.get("rec_boxes")
            if boxes is None:
                boxes = result.get("rec_polys") or []

            for i, text in enumerate(texts):
                if not text or not text.strip():
                    continue
                score = float(scores[i]) if i < len(scores) else 0.0

                if i < len(boxes) and len(boxes[i]) == 4 and not hasattr(boxes[i][0], "__len__"):
                    # rec_boxes: flat [x0, y0, x1, y1] in crop-local coords
                    bx0, by0, bx1, by1 = boxes[i]
                else:
                    # rec_polys: 4 corner points in crop-local coords
                    xs = [p[0] for p in boxes[i]] if i < len(boxes) else [0, crop.shape[1]]
                    ys = [p[1] for p in boxes[i]] if i < len(boxes) else [0, crop.shape[0]]
                    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)

                # translate crop-local bbox back to full-page coordinates
                page_bbox = [
                    float(x0 + bx0),
                    float(y0 + by0),
                    float(x0 + bx1),
                    float(y0 + by1),
                ]

                values.append(
                    {
                        "value": text.strip(),
                        "source": "paddleocr",
                        "confidence": score,
                        "page": page_number,
                        "bbox": page_bbox,
                        "role": region.get("role", "metadata"),
                        "category": region["category"],
                        # groups OCR output back to the specific table region
                        # it came from, so line_items.py can find a header
                        # row and map columns per-table rather than mixing
                        # text from unrelated tables/regions together
                        "region_id": f"{page_number}:{region['category']}:{region_index}",
                    }
                )

    return values
