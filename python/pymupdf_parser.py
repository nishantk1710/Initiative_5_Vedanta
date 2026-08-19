import pymupdf


def extract_with_pymupdf(page_info: dict, file_path: str) -> list[dict]:
    """Extract text blocks directly from a digitally-authored PDF page using
    PyMuPDF's structured text dict — no OCR involved for these pages, since
    the router already confirmed they carry a real text layer."""
    page_number = page_info["page"]
    blocks_out: list[dict] = []

    with pymupdf.open(file_path) as doc:
        page = doc[page_number - 1]
        raw = page.get_text("dict")

        for block in raw.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block, 1 = image block
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    blocks_out.append(
                        {
                            "value": text,
                            "source": "pymupdf",
                            "confidence": 1.0,  # exact digital text layer, not OCR'd
                            "page": page_number,
                            "bbox": [x0, y0, x1, y1],
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
