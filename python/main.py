import os

from dotenv import load_dotenv

# shared with the Next.js side — one .env.local at the repo root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pipeline import process_document, prepare_document
from paths import document_dir
import layout
import paddleocr_parser

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
def process(request: ProcessRequest):
    try:
        return process_document(request.document_id, request.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
    except Exception as exc:  # noqa: BLE001 - surface pipeline errors to the caller for now
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/page/{document_id}/{page_number}")
def get_page_image(document_id: str, page_number: int):
    safe_document_id = os.path.basename(document_id)
    image_path = os.path.join(
        document_dir(safe_document_id), "pages", f"page_{page_number:03d}.png"
    )
    if not os.path.isfile(image_path):
        raise HTTPException(status_code=404, detail=f"Page image not found: {image_path}")
    return FileResponse(image_path, media_type="image/png")
