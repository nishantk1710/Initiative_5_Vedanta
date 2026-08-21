"""Engine comparison ('Compare' tab): run two OCR engines against the same
rendered page and report their raw output side by side — text, latency,
confidence (or an honest "not available" when the engine doesn't expose
one), and a value count. A debugging/evaluation tool as much as an
end-user one: it answers "which engine handles this page better" without
requiring the whole pipeline to be re-run twice by hand.

Deliberately does not touch line_items.py/validator.py/llm.py — this is a
side-channel raw-OCR comparison, not an alternate extraction path, so it
can never affect the main pipeline's output.
"""

import time

import paddleocr_parser
import paddleocr_vl

SUPPORTED_ENGINES = ("paddleocr", "paddleocr_vl")

# Single source of truth for engine display metadata — the frontend fetches
# this via GET /engines rather than hardcoding engine names/labels or
# branching on an engine id string to decide whether it exposes confidence
# (see paddleocr_vl.py's module docstring for why VL doesn't: it's a single
# vision-language pass, not detection+recognition). Adding a third engine
# later means adding an entry here, not touching frontend components.
ENGINE_METADATA = {
    "paddleocr": {"name": "Classic PaddleOCR", "exposes_confidence": True},
    "paddleocr_vl": {"name": "PaddleOCR-VL-0.9B", "exposes_confidence": False},
}


def _is_engine_available(engine: str) -> bool:
    if engine == "paddleocr":
        return True  # the required baseline engine — always available once the service is up
    if engine == "paddleocr_vl":
        return paddleocr_vl.is_available()
    return False


def list_engines() -> list[dict]:
    """Real, current availability for every configured engine — paddleocr_vl's
    is_available() reflects whatever the VL microservice's own health check
    reported at this service's startup (see paddleocr_vl.py), never assumed."""
    return [
        {
            "id": engine_id,
            "name": meta["name"],
            "exposes_confidence": meta["exposes_confidence"],
            "available": _is_engine_available(engine_id),
        }
        for engine_id, meta in ENGINE_METADATA.items()
    ]


def _run_engine(engine: str, image_path: str, page_number: int) -> dict:
    if engine == "paddleocr_vl" and not paddleocr_vl.is_available():
        return {
            "engine": engine,
            "available": False,
            "reason": paddleocr_vl.unavailable_reason() or "PaddleOCR-VL was not initialized",
        }

    started = time.monotonic()
    try:
        if engine == "paddleocr":
            values = paddleocr_parser.ocr_full_page(image_path, page_number)
        elif engine == "paddleocr_vl":
            values = paddleocr_vl.ocr_full_page(image_path, page_number)
        else:
            raise ValueError(f"unsupported engine: {engine!r}")
    except RuntimeError as exc:
        # is_available() passed but the call itself still failed (a timeout,
        # a service that crashed mid-request, ...) — this must degrade this
        # ONE engine's result, not take down the whole /compare response
        # when other engines (or this one, on a retry) are still fine.
        return {"engine": engine, "available": False, "reason": str(exc)}
    latency_ms = (time.monotonic() - started) * 1000

    confidences = [v["confidence"] for v in values if v.get("confidence") is not None]
    # Never fabricate a confidence for an engine that has none for ANY of
    # its values — an average across a partial set would misrepresent an
    # engine that mostly doesn't expose one (see paddleocr_vl.py).
    confidence_available = len(confidences) == len(values) and len(values) > 0

    return {
        "engine": engine,
        "available": True,
        "latency_ms": round(latency_ms, 1),
        "value_count": len(values),
        "text": "\n".join(str(v["value"]) for v in values),
        "confidence_available": confidence_available,
        "average_confidence": (sum(confidences) / len(confidences)) if confidence_available else None,
        "values": values,
    }


def compare_engines(image_path: str, page_number: int, engines: list[str] | None = None) -> dict:
    """Run each requested engine (default: every supported engine) against
    the same page image and return their results side by side."""
    selected = engines or list(SUPPORTED_ENGINES)
    unknown = [e for e in selected if e not in SUPPORTED_ENGINES]
    if unknown:
        raise ValueError(f"unsupported engine(s): {unknown}")

    return {"page": page_number, "results": [_run_engine(e, image_path, page_number) for e in selected]}
