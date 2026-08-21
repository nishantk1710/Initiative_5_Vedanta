"""PaddleOCR-VL client (python/paddleocr_vl.py) — talks to the separate
python_vl_service/ microservice over HTTP. No real network/model calls here;
this tests the client's health-check/degrade-gracefully contract by faking
urllib's urlopen. See test_vl_service_values.py for the actual result-
flattening logic (which lives in the service, not this client).
"""

import json
from urllib.error import URLError

import paddleocr_vl


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reset(monkeypatch):
    monkeypatch.setattr(paddleocr_vl, "_available", False)
    monkeypatch.setattr(paddleocr_vl, "_unavailable_reason", None)


def test_is_available_false_before_warm_up(monkeypatch):
    _reset(monkeypatch)
    assert paddleocr_vl.is_available() is False


def test_warm_up_marks_available_when_health_check_succeeds(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(
        paddleocr_vl.urllib_request, "urlopen", lambda *a, **k: _FakeResponse({"available": True, "reason": None})
    )
    paddleocr_vl.warm_up()
    assert paddleocr_vl.is_available() is True
    assert paddleocr_vl.unavailable_reason() is None


def test_warm_up_marks_unavailable_when_service_reports_unavailable(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(
        paddleocr_vl.urllib_request,
        "urlopen",
        lambda *a, **k: _FakeResponse({"available": False, "reason": "model failed to load"}),
    )
    paddleocr_vl.warm_up()
    assert paddleocr_vl.is_available() is False
    assert "model failed to load" in paddleocr_vl.unavailable_reason()


def test_warm_up_does_not_raise_when_service_is_unreachable(monkeypatch):
    _reset(monkeypatch)

    def _raise(*a, **k):
        raise URLError("connection refused")

    monkeypatch.setattr(paddleocr_vl.urllib_request, "urlopen", _raise)

    paddleocr_vl.warm_up()  # must not raise

    assert paddleocr_vl.is_available() is False
    assert "unreachable" in paddleocr_vl.unavailable_reason()


def test_ocr_full_page_raises_clearly_when_unavailable(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(paddleocr_vl, "_unavailable_reason", "PaddleOCR-VL service unreachable: test")
    try:
        paddleocr_vl.ocr_full_page("some/path.png", page_number=1)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "unreachable" in str(exc)


def test_ocr_full_page_returns_values_from_service(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(paddleocr_vl, "_available", True)
    values_payload = [{"value": "Hello", "source": "paddleocr_vl", "confidence": None, "page": 1, "bbox": [0, 0, 1, 1]}]
    monkeypatch.setattr(
        paddleocr_vl.urllib_request, "urlopen", lambda *a, **k: _FakeResponse({"available": True, "values": values_payload})
    )
    result = paddleocr_vl.ocr_full_page("some/path.png", page_number=1)
    assert result == values_payload


def test_ocr_full_page_raises_when_service_reports_unavailable_mid_call(monkeypatch):
    """The health check at warm_up passed, but the service can still fail on
    an individual call (e.g. it crashed since) — that must surface clearly,
    not silently return an empty result."""
    _reset(monkeypatch)
    monkeypatch.setattr(paddleocr_vl, "_available", True)
    monkeypatch.setattr(
        paddleocr_vl.urllib_request,
        "urlopen",
        lambda *a, **k: _FakeResponse({"available": False, "reason": "engine crashed"}),
    )
    try:
        paddleocr_vl.ocr_full_page("some/path.png", page_number=1)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "engine crashed" in str(exc)
