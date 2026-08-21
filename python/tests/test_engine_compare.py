"""Engine comparison — mocked engines (no real OCR/model inference), just
the comparison contract: never fabricate confidence, report an engine as
unavailable honestly, latency always measured."""

import paddleocr_parser
import paddleocr_vl
from engine_compare import compare_engines, list_engines


def _classic_value(text, confidence):
    return {"value": text, "source": "paddleocr", "confidence": confidence, "page": 1, "bbox": [0, 0, 10, 10]}


def _vl_value(text):
    return {"value": text, "source": "paddleocr_vl", "confidence": None, "page": 1, "bbox": [0, 0, 10, 10]}


def test_classic_engine_reports_average_confidence(monkeypatch):
    monkeypatch.setattr(paddleocr_parser, "ocr_full_page", lambda path, page: [
        _classic_value("Total", 0.9), _classic_value("500", 0.8),
    ])
    result = compare_engines("fake.png", 1, engines=["paddleocr"])
    r = result["results"][0]
    assert r["confidence_available"] is True
    assert abs(r["average_confidence"] - 0.85) < 1e-9
    assert r["value_count"] == 2


def test_vl_engine_never_fabricates_confidence(monkeypatch):
    monkeypatch.setattr(paddleocr_vl, "is_available", lambda: True)
    monkeypatch.setattr(paddleocr_vl, "ocr_full_page", lambda path, page: [_vl_value("Total"), _vl_value("500")])
    result = compare_engines("fake.png", 1, engines=["paddleocr_vl"])
    r = result["results"][0]
    assert r["confidence_available"] is False
    assert r["average_confidence"] is None


def test_unavailable_engine_is_reported_honestly(monkeypatch):
    monkeypatch.setattr(paddleocr_vl, "is_available", lambda: False)
    monkeypatch.setattr(paddleocr_vl, "unavailable_reason", lambda: "no weights")
    result = compare_engines("fake.png", 1, engines=["paddleocr_vl"])
    r = result["results"][0]
    assert r["available"] is False
    assert r["reason"] == "no weights"


def test_unknown_engine_name_raises():
    try:
        compare_engines("fake.png", 1, engines=["not_a_real_engine"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_default_engines_run_both(monkeypatch):
    monkeypatch.setattr(paddleocr_parser, "ocr_full_page", lambda path, page: [_classic_value("A", 0.9)])
    monkeypatch.setattr(paddleocr_vl, "is_available", lambda: True)
    monkeypatch.setattr(paddleocr_vl, "ocr_full_page", lambda path, page: [_vl_value("A")])
    result = compare_engines("fake.png", 1)
    engines_seen = {r["engine"] for r in result["results"]}
    assert engines_seen == {"paddleocr", "paddleocr_vl"}


def test_latency_is_measured_not_fabricated(monkeypatch):
    monkeypatch.setattr(paddleocr_parser, "ocr_full_page", lambda path, page: [_classic_value("A", 0.9)])
    result = compare_engines("fake.png", 1, engines=["paddleocr"])
    assert result["results"][0]["latency_ms"] >= 0.0


def test_list_engines_reflects_real_vl_availability(monkeypatch):
    monkeypatch.setattr(paddleocr_vl, "is_available", lambda: True)
    engines = {e["id"]: e for e in list_engines()}
    assert engines["paddleocr"]["available"] is True
    assert engines["paddleocr"]["exposes_confidence"] is True
    assert engines["paddleocr_vl"]["available"] is True
    assert engines["paddleocr_vl"]["exposes_confidence"] is False


def test_list_engines_reports_vl_unavailable_honestly(monkeypatch):
    monkeypatch.setattr(paddleocr_vl, "is_available", lambda: False)
    engines = {e["id"]: e for e in list_engines()}
    assert engines["paddleocr_vl"]["available"] is False


def test_mid_call_failure_degrades_that_engine_not_the_whole_request(monkeypatch):
    """is_available() can pass and the call can still fail (timeout, the
    service crashing mid-request) — that must produce an honest
    unavailable result for just this engine, not raise out of
    compare_engines and take the whole /compare response down with it."""
    monkeypatch.setattr(paddleocr_vl, "is_available", lambda: True)
    monkeypatch.setattr(
        paddleocr_vl, "ocr_full_page", lambda path, page: (_ for _ in ()).throw(RuntimeError("service call failed: timed out"))
    )
    monkeypatch.setattr(paddleocr_parser, "ocr_full_page", lambda path, page: [_classic_value("A", 0.9)])

    result = compare_engines("fake.png", 1, engines=["paddleocr", "paddleocr_vl"])

    by_engine = {r["engine"]: r for r in result["results"]}
    assert by_engine["paddleocr"]["available"] is True
    assert by_engine["paddleocr_vl"]["available"] is False
    assert "timed out" in by_engine["paddleocr_vl"]["reason"]
