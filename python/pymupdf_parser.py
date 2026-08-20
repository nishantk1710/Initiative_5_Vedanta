import pymupdf

from metadata_extractor import is_line_item_text


def extract_with_pymupdf(page_info: dict, file_path: str) -> list[dict]:
    """Extract text blocks directly from a digitally-authored PDF page using
    PyMuPDF's structured text dict — no OCR involved for these pages, since
    the router already confirmed they carry a real text layer.

    Digital pages have no PP-StructureV3 layout detection, so there's no
    "table region" to confine line-item candidates to. Instead, each LINE
    (its spans joined) is classified once via the same is_line_item_text()
    heuristic used for scanned printed_text regions — a company letterhead
    or "GST No: ..." line is tagged role="metadata" and never reaches
    line_items.py, exactly like the scanned path."""
    page_number = page_info["page"]
    blocks_out: list[dict] = []

    with pymupdf.open(file_path) as doc:
        page = doc[page_number - 1]
        raw = page.get_text("dict")

        line_index = 0
        for block in raw.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block, 1 = image block
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue

                line_text = " ".join(s["text"] for s in spans)
                role = "line_item" if is_line_item_text(line_text) else "metadata"
                region_id = f"{page_number}:pymupdf_line:{line_index}"
                line_index += 1

                for span in spans:
                    x0, y0, x1, y1 = span["bbox"]
                    blocks_out.append(
                        {
                            "value": span["text"].strip(),
                            "source": "pymupdf",
                            "confidence": 1.0,  # exact digital text layer, not OCR'd
                            "page": page_number,
                            "bbox": [x0, y0, x1, y1],
                            "role": role,
                            "category": "text",
                            "region_id": region_id,
                        }
                    )

    return blocks_out


def get_page_dimensions(file_path: str, page_number: int) -> tuple[float, float]:
    """Page size in PDF points — the same coordinate space PyMuPDF's bbox
    values use, so (bbox / dimensions) gives a resolution-independent
    percentage regardless of the rendered PNG's actual pixel size."""
    with pymupdf.open(file_path) as doc:
        page = doc[page_number - 1]
        return page.rect.width, page.rect.height
