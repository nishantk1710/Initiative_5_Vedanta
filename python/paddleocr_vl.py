"""PaddleOCR-VL-0.9B client — talks to a SEPARATE microservice
(python_vl_service/, run under its own .venv_vl with paddlepaddle>=3.2.1)
instead of constructing the engine in this process.

Why a separate process: PaddleOCR-VL's safetensors weight loader only
handles bfloat16 natively on paddlepaddle>=3.2.0 — below that it falls back
through a numpy-based path, and numpy has no bfloat16 type, so it raises
`TypeError: data type 'bfloat16' not understood`. This service is pinned to
paddlepaddle==3.1.0 because PP-StructureV3's RT-DETR-based layout detector
hits a separate, unrelated Windows-CPU oneDNN/PIR bug on paddlepaddle>=3.2.
Both constraints are real and cannot be satisfied in one interpreter, so
PaddleOCR-VL runs in its own venv/process, reached over HTTP — see
python_vl_service/main.py for the service itself and requirements.lock.txt
for this service's frozen working versions (never change those to chase
PaddleOCR-VL; that's what the separate service is for).

This is an ADDITIONAL selectable engine, never a silent replacement — the
classic PaddleOCR path (paddleocr_parser.py) remains the default and keeps
working unchanged for every existing document. Callers that want to try the
VL engine pass engine="paddleocr_vl" explicitly (see extract_printed_with_engine
in paddleocr_parser.py and the /compare endpoint).

Same non-raising contract as before construction moved into the separate
service: any failure to reach or use it just disables this engine
(is_available() -> False) rather than crashing the pipeline — every call
site must check is_available() before relying on this engine.
"""

import json
import os
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

VL_SERVICE_URL = os.environ.get("PADDLEOCR_VL_SERVICE_URL", "http://127.0.0.1:8010")
HEALTH_TIMEOUT_SECONDS = 5
# CPU inference on a 0.9B vision-language model over a full page is
# genuinely slow — measured over 180s on a real page in this environment,
# not a hung request. This is not a "should be done by now" guard, just an
# outer bound so a truly dead/hung service doesn't block the caller forever.
OCR_TIMEOUT_SECONDS = 600

_available = False
_unavailable_reason: str | None = None


def warm_up() -> None:
    """Health-check the VL service now, at this service's own startup.
    Model construction happens inside the separate service's startup, not
    here — this only confirms it's reachable and reports what it says
    about itself. Never raises: an unreachable/unavailable VL service must
    not affect the classic PaddleOCR/Tesseract/PyMuPDF paths at all."""
    global _available, _unavailable_reason
    try:
        with urllib_request.urlopen(f"{VL_SERVICE_URL}/health", timeout=HEALTH_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        _available = bool(payload.get("available"))
        _unavailable_reason = None if _available else (payload.get("reason") or "PaddleOCR-VL service reported unavailable")
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        _available = False
        _unavailable_reason = f"PaddleOCR-VL service unreachable at {VL_SERVICE_URL}: {exc}"

    if not _available:
        print(f"[paddleocr_vl] {_unavailable_reason}")


def is_available() -> bool:
    return _available


def unavailable_reason() -> str | None:
    return _unavailable_reason


def ocr_full_page(image_path: str, page_number: int) -> list[dict]:
    """Same contract as paddleocr_parser.ocr_full_page, delegated to the
    separate VL service over HTTP. Raises RuntimeError if the service is
    unavailable or the call fails — callers must check is_available()
    first rather than relying on this to degrade silently."""
    if not _available:
        raise RuntimeError(unavailable_reason() or "PaddleOCR-VL service was not available at warm_up")

    body = json.dumps({"image_path": image_path, "page_number": page_number}).encode("utf-8")
    req = urllib_request.Request(
        f"{VL_SERVICE_URL}/ocr", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib_request.urlopen(req, timeout=OCR_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"PaddleOCR-VL service call failed: {exc}") from exc

    if not payload.get("available", True):
        raise RuntimeError(payload.get("reason") or "PaddleOCR-VL service reported unavailable")

    return payload["values"]
