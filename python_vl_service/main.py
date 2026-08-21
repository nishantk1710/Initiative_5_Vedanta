"""Standalone PaddleOCR-VL-0.9B microservice.

Why this is a SEPARATE process/venv from the main FastAPI service (python/
main.py, :8000): PaddleOCR-VL's safetensors weight loader only reads
bfloat16 weights natively on paddlepaddle>=3.2.0 — below that, it falls back
to a numpy-based path, and numpy has no bfloat16 type at all, so it raises
`TypeError: data type 'bfloat16' not understood`. But the main service is
pinned to paddlepaddle==3.1.0 because PP-StructureV3's RT-DETR-based layout
detector hits a DIFFERENT, unrelated bug on paddlepaddle>=3.2 (a Windows-CPU
oneDNN/PIR executor crash). Those two version requirements cannot both be
satisfied in one interpreter — see python/requirements.lock.txt for the
frozen working versions of the main service, which this must never touch.

Run under its own venv (.venv_vl) with paddlepaddle==3.2.1, on its own port
(8010 by default), entirely independent of the main service. If this
process is down, unreachable, or fails to construct the model, the main
service's paddleocr_vl.py client degrades gracefully — every other engine
(PP-StructureV3, classic PaddleOCR, Tesseract, PyMuPDF) is completely
unaffected.

    .venv_vl/Scripts/python.exe -m uvicorn main:app --port 8010

(run from this directory, so `main` resolves to this file).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

_vl_engine = None
_unavailable_reason: str | None = None


def _construct_engine():
    from paddleocr import PaddleOCRVL

    return PaddleOCRVL()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _vl_engine, _unavailable_reason
    print("[paddleocr_vl_service] Constructing PaddleOCR-VL-0.9B...")
    try:
        _vl_engine = _construct_engine()
        print("[paddleocr_vl_service] Ready.")
    except Exception as exc:  # noqa: BLE001 - never let a construction failure crash this service
        _unavailable_reason = f"PaddleOCR-VL unavailable: {exc}"
        print(f"[paddleocr_vl_service] {_unavailable_reason}")
    yield


app = FastAPI(title="PaddleOCR-VL Service", lifespan=lifespan)


class OcrRequest(BaseModel):
    image_path: str
    page_number: int


@app.get("/health")
def health():
    return {"status": "ok", "available": _vl_engine is not None, "reason": _unavailable_reason}


def _collect_vl_values(vl_result, page_number: int) -> list[dict]:
    """Flatten a PaddleOCRVL predict() result into ExtractedValue-shaped
    dicts — mirrors python/paddleocr_vl.py's _collect_vl_values exactly
    (kept as a separate copy here since this service can't import across
    the venv boundary). Keep the two in sync if this shape ever changes.

    There is no per-block confidence anywhere in PaddleOCRVLBlock — it's a
    single vision-language pass, not detection+recognition — so every
    value is tagged confidence=None / confidence_available=False rather
    than a fabricated number.
    """
    values: list[dict] = []
    blocks = vl_result["parsing_res_list"]
    for block in blocks:
        text = str(getattr(block, "content", "") or "").strip()
        if not text:
            continue
        bbox = getattr(block, "bbox", None)
        if not bbox or len(bbox) != 4:
            continue
        bx0, by0, bx1, by1 = bbox
        values.append(
            {
                "value": text,
                "source": "paddleocr_vl",
                "confidence": None,
                "confidence_available": False,
                "page": page_number,
                "bbox": [float(bx0), float(by0), float(bx1), float(by1)],
                "block_label": getattr(block, "label", None),
            }
        )
    return values


@app.post("/ocr")
def ocr(request: OcrRequest):
    if _vl_engine is None:
        return {"available": False, "reason": _unavailable_reason or "PaddleOCR-VL was not initialized"}

    results = _vl_engine.predict(request.image_path)
    values: list[dict] = []
    for result in results:
        values.extend(_collect_vl_values(result, request.page_number))
    return {"available": True, "values": values}
