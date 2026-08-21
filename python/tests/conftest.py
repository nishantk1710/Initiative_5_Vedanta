"""Shared fixtures.

Documents are generated deterministically rather than committed as binaries,
so a fixture's exact content is visible in code and reviewable in a diff.
Anything genuinely un-generatable (a real photographed receipt) stays a
committed sample under public/samples or uploads.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON_DIR = os.path.join(REPO_ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


def _field(value, *, source="paddleocr", confidence=0.97, page=1, bbox=None):
    """Build one LineItem field in the canonical ExtractedValue shape."""
    return {
        "value": value,
        "source": source,
        "confidence": confidence,
        "page": page,
        "bbox": list(bbox or [0, 0, 10, 10]),
    }


@pytest.fixture
def field():
    return _field


def _row(**fields):
    """Build a LineItem row from keyword fields; omitted keys stay ABSENT
    (not None) to match LineItem's optional-field contract."""
    return {name: _field(value) if not isinstance(value, dict) else value for name, value in fields.items()}


@pytest.fixture
def row():
    return _row


@pytest.fixture(scope="session")
def repo_root():
    return REPO_ROOT


@pytest.fixture(scope="session")
def samples_dir(repo_root):
    return os.path.join(repo_root, "public", "samples")


@pytest.fixture(scope="session")
def llm_configured():
    """True when .env supplies live Azure credentials."""
    from dotenv import load_dotenv

    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    import llm_client

    return llm_client.is_configured()


# --------------------------------------------------------------------------
# Synthetic document generation
# --------------------------------------------------------------------------

def _text_pdf(path: str, pages: list[str]) -> str:
    """A real digital PDF with a genuine text layer (router -> 'digital')."""
    import pymupdf

    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def _image_pdf(path: str, renderers: list) -> str:
    """A PDF whose pages are pure images — no text layer at all, so the
    router must classify them 'scanned' and send them through OCR."""
    import pymupdf
    from PIL import Image

    tmp_pngs = []
    doc = pymupdf.open()
    for i, render in enumerate(renderers):
        img: Image.Image = render()
        png = f"{path}.page{i}.png"
        img.save(png)
        tmp_pngs.append(png)
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=png)
    doc.save(path)
    doc.close()
    for png in tmp_pngs:
        os.remove(png)
    return path


def _grid_table_image(title: str, headers: list[str], rows: list[list[str]], width=1700, height=2200):
    """A bordered table — the case PP-StructureV3 detects as a real table."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("arial.ttf", 42)
        font = ImageFont.truetype("arial.ttf", 30)
    except Exception:
        font_title = font = ImageFont.load_default()

    draw.text((100, 80), title, font=font_title, fill="black")
    x0, y0 = 100, 200
    col_w = [700, 250, 200, 250, 250][: len(headers)]
    # widen last column if fewer headers than the default 5-col layout
    if len(col_w) < len(headers):
        col_w += [250] * (len(headers) - len(col_w))
    row_h = 80
    total_w = sum(col_w)
    n = len(rows) + 1

    for r in range(n + 1):
        y = y0 + r * row_h
        draw.line([(x0, y), (x0 + total_w, y)], fill="black", width=3)
    x = x0
    for w in [0] + col_w:
        x += w
        draw.line([(x, y0), (x, y0 + n * row_h)], fill="black", width=3)

    x = x0
    for i, h in enumerate(headers):
        draw.text((x + 15, y0 + 20), h, font=font, fill="black")
        x += col_w[i]
    for ri, r in enumerate(rows):
        x = x0
        y = y0 + (ri + 1) * row_h
        for ci, cell in enumerate(r):
            draw.text((x + 15, y + 20), cell, font=font, fill="black")
            x += col_w[ci]
    return img


def _plain_lines_image(lines: list[str], width=900, height=1400, size=24):
    """Borderless text lines — no grid, so layout detection finds no table."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        font = ImageFont.load_default()
    y = 40
    for line in lines:
        draw.text((30, y), line, font=font, fill="black")
        y += int(size * 1.7)
    return img


@pytest.fixture(scope="session")
def docs(tmp_path_factory):
    """Session-scoped synthetic corpus. Returns {name: pdf_path}.

    Covers the scenarios from the spec that can be generated deterministically;
    each entry names the scenario it exercises.
    """
    d = tmp_path_factory.mktemp("docs")
    out = {}

    # (1) digital invoice — real text layer
    out["digital_invoice"] = _text_pdf(
        str(d / "digital_invoice.pdf"),
        [
            "TAX INVOICE\nAcme Supplies Ltd\nGST NO: 27AAAAA0000A1Z5\n"
            "Bill No: INV-2024-77  Date: 04/03/2024\n\n"
            "Description   Qty   Unit   Rate   Amount\n"
            "Steel bolts     10   box     50      500\n"
            "Copper wire      4   roll   125      500\n"
        ],
    )

    # (13) PDF with a junk text layer — dot leaders / underscores only.
    # router.is_meaningful_text() must NOT call this 'digital'.
    out["junk_text_layer"] = _text_pdf(
        str(d / "junk_text_layer.pdf"),
        ["...................................................\n____________________\n7\n"],
    )

    # (3) BOQ — bordered table, English headers (deterministic path)
    out["boq"] = _image_pdf(
        str(d / "boq.pdf"),
        [
            lambda: _grid_table_image(
                "BILL OF QUANTITIES",
                ["Description", "Quantity", "Unit", "Rate", "Amount"],
                [
                    ["Site clearing", "12.5", "Ha", "5000", "62500"],
                    ["Overburden removal", "45000", "m3", "12", "540000"],
                ],
            )
        ],
    )

    # (5) German table — bordered, non-English headers. Deterministic column
    # matching is English-only, so this must fall through to the LLM path.
    out["german_table"] = _image_pdf(
        str(d / "german_table.pdf"),
        [
            lambda: _grid_table_image(
                "RECHNUNG",
                ["Bezeichnung", "Menge", "Einheit", "Preis", "Betrag"],
                [
                    ["Bio Vollkornbrot", "2", "Stk", "3.50", "7.00"],
                    ["Kaffee Latte", "1", "Stk", "3.80", "3.80"],
                ],
            )
        ],
    )

    # (6) bank statement — a table that is NOT line items. The system must not
    # assume every table is an invoice item table.
    out["bank_statement"] = _image_pdf(
        str(d / "bank_statement.pdf"),
        [
            lambda: _grid_table_image(
                "ACCOUNT STATEMENT",
                ["Date", "Description", "Debit", "Credit", "Balance"],
                [
                    ["01/03/2024", "Opening balance", "", "", "10000"],
                    ["03/03/2024", "ATM withdrawal", "500", "", "9500"],
                ],
            )
        ],
    )

    # (4) borderless receipt — no grid at all
    out["borderless_receipt"] = _image_pdf(
        str(d / "borderless_receipt.pdf"),
        [
            lambda: _plain_lines_image(
                [
                    "QUICK MART",
                    "Bill No: 4471",
                    "--------------------------------",
                    "Item              Qty      Amount",
                    "Bread               2        60",
                    "Milk 1L             1        55",
                    "--------------------------------",
                    "Total                       115",
                ]
            )
        ],
    )

    # (7) resume — no tables, no invoice metadata whatsoever
    out["resume"] = _text_pdf(
        str(d / "resume.pdf"),
        [
            "JOHN SMITH\njohn.smith@example.com | +1 555 0100 | Berlin\n\n"
            "SUMMARY\nBackend engineer with eight years of experience.\n\n"
            "EXPERIENCE\nSenior Engineer, Globex 2019-2024\nEngineer, Initech 2016-2019\n\n"
            "EDUCATION\nBSc Computer Science, TU Berlin\n\nSKILLS\nPython, Go, PostgreSQL\n"
        ],
    )

    # (8) contract — prose only
    out["contract"] = _text_pdf(
        str(d / "contract.pdf"),
        [
            "SERVICE AGREEMENT\n\nThis agreement is made between Alpha Ltd and Beta Inc "
            "on the fourth of March, two thousand twenty four.\n\n"
            "1. SCOPE\nThe supplier shall provide maintenance services.\n\n"
            "2. TERM\nThis agreement remains in force for twelve months.\n"
        ],
    )

    # (9) generic unknown document
    out["unknown_doc"] = _text_pdf(
        str(d / "unknown_doc.pdf"),
        [
            "FIELD OBSERVATION LOG\n\nWeather was overcast for most of the morning. "
            "The team recorded ambient readings at three separate stations and noted "
            "no unusual variance across the sampled interval.\n"
        ],
    )

    # (11) multi-page continuation table — same schema across both pages
    out["multipage_table"] = _image_pdf(
        str(d / "multipage_table.pdf"),
        [
            lambda: _grid_table_image(
                "BILL OF QUANTITIES - PAGE 1",
                ["Description", "Quantity", "Unit", "Rate", "Amount"],
                [["Site clearing", "12.5", "Ha", "5000", "62500"]],
            ),
            lambda: _grid_table_image(
                "BILL OF QUANTITIES - PAGE 2",
                ["Description", "Quantity", "Unit", "Rate", "Amount"],
                [["Blasting", "300", "holes", "800", "240000"]],
            ),
        ],
    )

    # (24) mixed digital + scanned in one PDF
    import pymupdf

    mixed = str(d / "mixed_pages.pdf")
    doc = pymupdf.open()
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((72, 72), "SCOPE OF WORK\nThis page has a real digital text layer "
                             "with several genuine sentences of body copy.", fontsize=11)
    png = str(d / "_mixed_scan.png")
    _grid_table_image(
        "BILL OF QUANTITIES",
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [["Haul road", "3.2", "km", "25000", "80000"]],
    ).save(png)
    p2 = doc.new_page(width=612, height=792)
    p2.insert_image(p2.rect, filename=png)
    doc.save(mixed)
    doc.close()
    os.remove(png)
    out["mixed_pages"] = mixed

    # (19) table with NO recognizable headers
    out["table_no_headers"] = _image_pdf(
        str(d / "table_no_headers.pdf"),
        [
            lambda: _grid_table_image(
                "DATA",
                ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"],
                [["foo", "1", "x", "2", "3"], ["bar", "4", "y", "5", "6"]],
            )
        ],
    )

    # (20) table with exactly ONE recognizable header -> 'incomplete', not a guess
    out["table_one_header"] = _image_pdf(
        str(d / "table_one_header.pdf"),
        [
            lambda: _grid_table_image(
                "PARTIAL",
                ["Description", "Alpha", "Beta", "Gamma", "Delta"],
                [["widget", "1", "x", "2", "3"]],
            )
        ],
    )

    # (23) multi-column page — reading order must not interleave columns
    def _two_column():
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1700, 2200), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except Exception:
            font = ImageFont.load_default()
        left = ["LEFT COLUMN", "First left line", "Second left line", "Third left line"]
        right = ["RIGHT COLUMN", "First right line", "Second right line", "Third right line"]
        y = 200
        for a, b in zip(left, right):
            draw.text((120, y), a, font=font, fill="black")
            draw.text((950, y), b, font=font, fill="black")
            y += 90
        return img

    out["multi_column"] = _image_pdf(str(d / "multi_column.pdf"), [_two_column])

    # (12) image input — a bare PNG, not a PDF (PyMuPDF opens it as 1 page)
    png_path = str(d / "receipt_image.png")
    _grid_table_image(
        "CASH BILL",
        ["Description", "Quantity", "Unit", "Rate", "Amount"],
        [["Cement bag", "10", "bag", "350", "3500"]],
    ).save(png_path)
    out["image_input"] = png_path

    return out
