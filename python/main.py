import os

from dotenv import load_dotenv

# Single source of truth: one .env at the repo root, shared with the Next.js
# side. Deliberately does NOT also read .env.local — having two files where
# one silently overrides the other is how empty placeholder values end up
# shadowing real credentials.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pipeline import process_document, prepare_document
from paths import document_dir
from progress import read_progress, write_queued
from router import inspect_document
from engine_compare import compare_engines, list_engines
import layout
import paddleocr_parser
import paddleocr_vl

app = FastAPI(title="Mining SOW BOQ Extractor - Python Service")


@app.on_event("startup")
def warm_up_engines():
    # Pays the one-time, CPU-bound cost of constructing PP-StructureV3's
    # ~13 sub-models and the PaddleOCR engine now, during startup (visible
    # in this log), instead of on the first /process call — which was
    # otherwise slow enough to trip a request timeout.
    print("[startup] Warming up PP-StructureV3 and PaddleOCR engines...")
    layout.warm_up()
    paddleocr_parser.warm_up()
    print("[startup] Engines ready.")

    # Best-effort: PaddleOCR-VL is an additional, optional engine (see
    # paddleocr_vl.py) — its warm_up() already swallows its own failures
    # and just leaves is_available() False, but startup must survive even
    # an unexpected exception here rather than taking down the classic
    # PaddleOCR/Tesseract/PyMuPDF paths that don't depend on it at all.
    print("[startup] Warming up PaddleOCR-VL (optional engine)...")
    try:
        paddleocr_vl.warm_up()
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] PaddleOCR-VL warm-up failed unexpectedly: {exc}")
    print(
        "[startup] PaddleOCR-VL ready."
        if paddleocr_vl.is_available()
        else f"[startup] PaddleOCR-VL unavailable: {paddleocr_vl.unavailable_reason()}"
    )


class ProcessRequest(BaseModel):
    document_id: str
    file_path: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/prepare")
def prepare(request: ProcessRequest):
    try:
        return prepare_document(request.document_id, request.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/process")
def process(request: ProcessRequest, background_tasks: BackgroundTasks):
    """Async job model: a 10+ page scanned document can genuinely take
    10-15+ minutes, which would time out any synchronous HTTP call. This
    returns IMMEDIATELY with the job's real page count (from
    inspect_document() — never hardcoded or guessed) while the actual
    pipeline runs as a FastAPI background task. GET /status/{document_id}
    reports real, per-page progress as that background task genuinely
    reaches each page/stage — see progress.py.

    job_id == document_id: this deployment is single-process/single-worker
    (see progress.py's module docstring), so there's no need for a separate
    job-id scheme on top of the document id that already anchors every
    other per-document file (results/<id>/...).
    """
    try:
        pages = inspect_document(request.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))

    pages_total = len(pages)
    # Written synchronously, before the background task even starts, so a
    # client that polls GET /status immediately after this response never
    # 404s waiting for the background job's own tracker to construct.
    write_queued(request.document_id, pages_total)

    def _run_in_background() -> None:
        try:
            process_document(request.document_id, request.file_path)
        except Exception as exc:  # noqa: BLE001 - already recorded to progress.json via tracker.fail()
            print(f"[process:{request.document_id}] background job failed: {exc}")

    background_tasks.add_task(_run_in_background)

    return {"job_id": request.document_id, "status": "queued", "pages_total": pages_total}


@app.get("/status/{document_id}")
def status(document_id: str):
    safe_document_id = os.path.basename(document_id)
    progress = read_progress(safe_document_id)
    if progress is None:
        raise HTTPException(status_code=404, detail=f"No progress recorded for {safe_document_id}")
    return progress


@app.get("/engines")
def engines():
    """Real, current OCR engines this service can run — see
    engine_compare.py's ENGINE_METADATA. The frontend renders its engine
    toggle by mapping over this rather than hardcoding engine names/ids, so
    adding a third engine is a backend config change, not a frontend one."""
    return {"engines": list_engines()}


@app.get("/compare/{document_id}/{page_number}")
def compare(document_id: str, page_number: int, engines: str | None = None):
    """Run two (or more) OCR engines on the same rendered page and return
    their raw output side by side — see engine_compare.py. `engines` is a
    comma-separated list (e.g. "paddleocr,paddleocr_vl"); omit for the
    default set."""
    safe_document_id = os.path.basename(document_id)
    image_path = os.path.join(
        document_dir(safe_document_id), "pages", f"page_{page_number:03d}.png"
    )
    if not os.path.isfile(image_path):
        raise HTTPException(status_code=404, detail=f"Page image not found: {image_path}")

    engine_list = [e.strip() for e in engines.split(",")] if engines else None
    try:
        return compare_engines(image_path, page_number, engine_list)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/page/{document_id}/{page_number}")
def get_page_image(document_id: str, page_number: int):
    safe_document_id = os.path.basename(document_id)
    image_path = os.path.join(
        document_dir(safe_document_id), "pages", f"page_{page_number:03d}.png"
    )
    if not os.path.isfile(image_path):
        raise HTTPException(status_code=404, detail=f"Page image not found: {image_path}")
    return FileResponse(image_path, media_type="image/png")
