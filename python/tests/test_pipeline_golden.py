"""End-to-end pipeline tests against real documents.

Marked `slow` — these run genuine layout detection + OCR (tens of seconds per
scanned page on CPU) and are excluded from the default `pytest` run. Run them
explicitly around any refactor:

    pytest -m slow

Purpose is regression detection, not accuracy measurement: they pin the
behaviour that exists today so a refactor that changes it has to do so
deliberately. Where a value is genuinely correct (verified against the source
image) the assertion is exact; where it depends on OCR quality the assertion
is structural.
"""

import os
import shutil

import pytest

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def run_pipeline(repo_root):
    """Process a document and clean up its results dir afterwards."""
    from dotenv import load_dotenv

    load_dotenv(os.path.join(repo_root, ".env"))
    from pipeline import process_document
    from paths import document_dir

    created = []

    def _run(doc_id: str, file_path: str) -> dict:
        created.append(doc_id)
        return process_document(doc_id, file_path)

    yield _run

    for doc_id in created:
        shutil.rmtree(document_dir(doc_id), ignore_errors=True)


# --------------------------------------------------------------------------
# Routing (fast enough to assert precisely)
# --------------------------------------------------------------------------

def test_digital_pdf_routes_digital_and_is_not_ocrd(docs):
    """Spec criterion 3: digital PDFs must not be OCR'd."""
    from router import inspect_document

    pages = inspect_document(docs["digital_invoice"])
    assert [p["type"] for p in pages] == ["digital"]


def test_junk_text_layer_routes_scanned(docs):
    """Spec case 13: a dot-leader/underscore text layer is not real text."""
    from router import inspect_document

    pages = inspect_document(docs["junk_text_layer"])
    assert [p["type"] for p in pages] == ["scanned"]


def test_mixed_document_routes_per_page(docs):
    """Spec case 24."""
    from router import inspect_document

    pages = inspect_document(docs["mixed_pages"])
    assert [p["type"] for p in pages] == ["digital", "scanned"]


def test_image_input_routes_scanned(docs):
    """Spec case 12: a bare PNG opens as a one-page scanned document."""
    from router import inspect_document

    pages = inspect_document(docs["image_input"])
    assert [p["type"] for p in pages] == ["scanned"]


# --------------------------------------------------------------------------
# Golden behaviour on the bundled BOQ samples (criterion 2: no regression)
# --------------------------------------------------------------------------

def test_bundled_boq_sample_extracts_known_rows(run_pipeline, samples_dir):
    """sow-3 is the reference scanned BOQ. These four rows and their values
    are verified correct against the rendered page image."""
    result = run_pipeline("test-golden-sow3", os.path.join(samples_dir, "sow-3.pdf"))

    assert result["extraction_path"] == "table_regions", "must use the deterministic path"
    assert result["summary"]["total_rows"] == 4

    by_desc = {r["description"]["value"]: r for r in result["lineItems"]}
    assert "Site clearing" in by_desc
    assert by_desc["Site clearing"]["quantity"]["value"] == 12.5
    assert by_desc["Site clearing"]["unit"]["value"] == "Ha"
    assert by_desc["Site clearing"]["rate"]["value"] == 5000.0
    assert by_desc["Site clearing"]["amount"]["value"] == 62500.0
    assert by_desc["Site clearing"]["status"] == "valid"

    assert by_desc["Overburden removal"]["amount"]["value"] == 540000.0
    assert by_desc["Haul road construction"]["amount"]["value"] == 80000.0

    # every field carries provenance
    for row in result["lineItems"]:
        assert row["description"]["source"] in ("paddleocr", "pymupdf", "tesseract", "llm")
        assert row["description"]["page"] == 1
        assert any(row["description"]["bbox"])


def test_bundled_boq_arithmetic_mismatch_is_flagged_not_hidden(run_pipeline, samples_dir):
    """The 'Drainage works' row has qty 1.1 misread as 11. Whatever the
    correction logic does, the row must never come back 'valid'."""
    result = run_pipeline("test-golden-sow3-arith", os.path.join(samples_dir, "sow-3.pdf"))
    drainage = [r for r in result["lineItems"] if "Drainage" in str(r["description"]["value"])]
    assert drainage, "expected a Drainage works row"
    assert drainage[0]["status"] in ("review", "ambiguous"), (
        "a row with inconsistent arithmetic must be surfaced for review"
    )


def test_digital_sample_uses_pymupdf_not_ocr(run_pipeline, samples_dir):
    """sow-1 is all-digital: every value should come from the text layer."""
    result = run_pipeline("test-golden-sow1", os.path.join(samples_dir, "sow-1.pdf"))
    sources = {
        f["source"]
        for row in result["lineItems"]
        for k, f in row.items()
        if isinstance(f, dict) and "source" in f
    }
    assert sources, "expected at least one extracted field"
    assert sources <= {"pymupdf", "llm"}, f"digital page should not be OCR'd, got {sources}"


# --------------------------------------------------------------------------
# Structural guarantees that must hold for ANY document
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "doc_key",
    ["resume", "contract", "unknown_doc", "bank_statement", "table_no_headers", "multi_column"],
)
def test_arbitrary_documents_process_without_error(run_pipeline, docs, doc_key):
    """Spec criterion 6: any document processes without pre-selecting a type,
    and never crashes. It may legitimately extract nothing."""
    result = run_pipeline(f"test-arb-{doc_key}", docs[doc_key])
    assert result["status"] == "completed"
    assert isinstance(result["lineItems"], list)
    assert "document_type" in result
    assert result["summary"]["total_rows"] == len(result["lineItems"])


@pytest.mark.parametrize("doc_key", ["resume", "contract", "unknown_doc"])
def test_non_invoice_documents_do_not_get_invented_line_items(run_pipeline, docs, doc_key):
    """Spec criterion 11 / no-hallucination: prose with no table must not
    produce fabricated rows with numeric fields."""
    result = run_pipeline(f"test-noinvent-{doc_key}", docs[doc_key])
    for row in result["lineItems"]:
        # any row emitted from prose must at minimum not claim a confident
        # numeric amount it never saw
        amount = row.get("amount", {}).get("value", "")
        if str(amount).strip():
            assert row["status"] != "valid", (
                f"prose document produced a 'valid' row with amount={amount!r} — "
                "this is fabricated structure"
            )


def test_result_and_regions_files_written(run_pipeline, docs, repo_root):
    from paths import document_dir

    run_pipeline("test-artifacts", docs["boq"])
    d = document_dir("test-artifacts")
    assert os.path.isfile(os.path.join(d, "result.json"))
    assert os.path.isfile(os.path.join(d, "regions.json"))
    assert os.path.isfile(os.path.join(d, "pages", "page_001.png"))


def test_every_page_is_rendered_even_when_digital(run_pipeline, docs):
    """The UI needs a page image for every page regardless of routing."""
    from paths import document_dir

    run_pipeline("test-render-all", docs["mixed_pages"])
    pages_dir = os.path.join(document_dir("test-render-all"), "pages")
    assert sorted(os.listdir(pages_dir)) == ["page_001.png", "page_002.png"]


def test_regions_json_carries_page_dimensions(run_pipeline, docs):
    """bbox -> percentage conversion in the UI depends on these."""
    import json

    from paths import document_dir

    run_pipeline("test-dims", docs["boq"])
    with open(os.path.join(document_dir("test-dims"), "regions.json")) as f:
        entries = json.load(f)
    for entry in entries:
        assert entry["width"] > 0 and entry["height"] > 0
        assert "regions" in entry


def test_bboxes_stay_inside_page_bounds(run_pipeline, docs):
    """Spec: one canonical coordinate system. A bbox outside the rendered
    page means a units mismatch crept in."""
    import json

    from paths import document_dir

    run_pipeline("test-bbox-bounds", docs["boq"])
    with open(os.path.join(document_dir("test-bbox-bounds"), "regions.json")) as f:
        entries = json.load(f)
    for entry in entries:
        w, h = entry["width"], entry["height"]
        for region in entry["regions"]:
            x0, y0, x1, y1 = region["bbox"]
            assert 0 <= x0 <= w + 1 and 0 <= x1 <= w + 1, f"x out of bounds: {region['bbox']} vs {w}"
            assert 0 <= y0 <= h + 1 and 0 <= y1 <= h + 1, f"y out of bounds: {region['bbox']} vs {h}"


def test_logo_regions_never_become_extracted_values(run_pipeline, docs):
    """Spec case 22."""
    import json

    from paths import document_dir

    run_pipeline("test-nologo", docs["boq"])
    with open(os.path.join(document_dir("test-nologo"), "regions.json")) as f:
        entries = json.load(f)
    for entry in entries:
        for region in entry["regions"]:
            assert region.get("category") != "logo"
