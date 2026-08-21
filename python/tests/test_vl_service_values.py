"""python_vl_service/main.py's _collect_vl_values — the result-flattening
logic that used to live in python/paddleocr_vl.py before PaddleOCR-VL moved
into its own microservice/venv (see paddleocr_vl.py's module docstring for
why). Imported by explicit path since python_vl_service/ isn't on this
suite's pythonpath (it belongs to a separate venv with its own,
incompatible paddlepaddle version) — this only exercises the pure Python
flattening logic, no paddle/fastapi import required.
"""

import importlib.util
import os

_SERVICE_MAIN = os.path.join(os.path.dirname(__file__), "..", "..", "python_vl_service", "main.py")
_spec = importlib.util.spec_from_file_location("_vl_service_main_under_test", _SERVICE_MAIN)
vl_service_main = importlib.util.module_from_spec(_spec)


class _StubFastAPI:
    def __init__(self, *a, **k):
        pass

    def get(self, *a, **k):
        return lambda fn: fn

    def post(self, *a, **k):
        return lambda fn: fn


import sys
import types

_fake_fastapi = types.ModuleType("fastapi")
_fake_fastapi.FastAPI = _StubFastAPI
_fake_pydantic = types.ModuleType("pydantic")
_fake_pydantic.BaseModel = object
sys.modules.setdefault("fastapi", _fake_fastapi)
sys.modules.setdefault("pydantic", _fake_pydantic)

_spec.loader.exec_module(vl_service_main)


class _FakeBlock:
    def __init__(self, label, content, bbox):
        self.label = label
        self.content = content
        self.bbox = bbox


def _fake_result(blocks):
    return {"parsing_res_list": blocks}


def test_confidence_is_never_fabricated():
    result = _fake_result([_FakeBlock("text", "Total: 500", [10, 10, 100, 30])])
    values = vl_service_main._collect_vl_values(result, page_number=1)
    assert len(values) == 1
    assert values[0]["confidence"] is None
    assert values[0]["confidence_available"] is False


def test_source_is_tagged_paddleocr_vl():
    result = _fake_result([_FakeBlock("text", "Hello", [0, 0, 10, 10])])
    values = vl_service_main._collect_vl_values(result, page_number=1)
    assert values[0]["source"] == "paddleocr_vl"


def test_empty_content_blocks_are_skipped():
    result = _fake_result([_FakeBlock("text", "   ", [0, 0, 10, 10]), _FakeBlock("text", "Real text", [0, 20, 10, 30])])
    values = vl_service_main._collect_vl_values(result, page_number=1)
    assert len(values) == 1
    assert values[0]["value"] == "Real text"


def test_blocks_missing_bbox_are_skipped():
    result = _fake_result([_FakeBlock("text", "no bbox", None)])
    values = vl_service_main._collect_vl_values(result, page_number=1)
    assert values == []


def test_bbox_is_passed_through_as_floats():
    result = _fake_result([_FakeBlock("text", "Hello", [0, 0, 10, 10])])
    values = vl_service_main._collect_vl_values(result, page_number=1)
    assert values[0]["bbox"] == [0.0, 0.0, 10.0, 10.0]


def test_health_reports_unavailable_before_construction():
    vl_service_main._vl_engine = None
    vl_service_main._unavailable_reason = "boom"
    result = vl_service_main.health()
    assert result == {"status": "ok", "available": False, "reason": "boom"}
