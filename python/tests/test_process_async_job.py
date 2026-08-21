"""POST /process's async job contract: returns immediately with the REAL
page count, runs the actual pipeline as a background task, and GET /status
reports real per-page progress. Mocks pipeline.process_document itself
(and the module-startup engine warm-ups) — this suite is about the job/
status contract, not re-testing the pipeline's own extraction logic (that's
test_pipeline_golden.py etc.).
"""

import pytest
from fastapi.testclient import TestClient

import layout
import main
import paddleocr_parser
import paddleocr_vl
import progress


@pytest.fixture(autouse=True)
def _isolate_progress_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    monkeypatch.setattr(main, "document_dir", lambda doc_id: str(tmp_path))


@pytest.fixture
def client(monkeypatch):
    # Skip the real engine warm-up (PP-StructureV3/PaddleOCR/PaddleOCR-VL
    # construction, minutes of real model loading) — the FastAPI startup
    # event runs warm_up_engines() the moment TestClient's context manager
    # opens, and this suite is about the /process job/status contract, not
    # re-testing that startup path.
    monkeypatch.setattr(layout, "warm_up", lambda: None)
    monkeypatch.setattr(paddleocr_parser, "warm_up", lambda: None)
    monkeypatch.setattr(paddleocr_vl, "warm_up", lambda: None)
    with TestClient(main.app) as c:
        yield c


def test_process_returns_immediately_with_real_page_count(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "inspect_document", lambda path: [{"page": 1, "type": "digital"}, {"page": 2, "type": "scanned"}])
    monkeypatch.setattr(main, "process_document", lambda doc_id, path: None)

    (tmp_path / "fake.pdf").write_bytes(b"%PDF-1.4 fake")
    response = client.post("/process", json={"document_id": "doc1", "file_path": str(tmp_path / "fake.pdf")})

    assert response.status_code == 200
    body = response.json()
    assert body == {"job_id": "doc1", "status": "queued", "pages_total": 2}


def test_process_404s_when_file_missing(client, monkeypatch):
    def _raise(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(main, "inspect_document", _raise)
    response = client.post("/process", json={"document_id": "doc1", "file_path": "does/not/exist.pdf"})
    assert response.status_code == 404


def test_status_reports_queued_before_background_job_starts(client, monkeypatch, tmp_path):
    """write_queued() must land on disk synchronously, before the endpoint
    even returns, so a client polling immediately after never 404s."""
    monkeypatch.setattr(main, "inspect_document", lambda path: [{"page": 1, "type": "digital"}])

    # A background task that never actually runs (simulating the real
    # world's async gap) — status must still be readable right after the
    # POST response, from write_queued() alone.
    monkeypatch.setattr(main, "process_document", lambda doc_id, path: None)
    original_add_task = main.BackgroundTasks.add_task
    captured = {}

    def _capture_instead_of_running(self, func, *a, **k):
        captured["func"] = func  # don't actually invoke it yet

    monkeypatch.setattr(main.BackgroundTasks, "add_task", _capture_instead_of_running)

    (tmp_path / "fake.pdf").write_bytes(b"%PDF-1.4 fake")
    client.post("/process", json={"document_id": "doc1", "file_path": str(tmp_path / "fake.pdf")})

    status_response = client.get("/status/doc1")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"

    monkeypatch.setattr(main.BackgroundTasks, "add_task", original_add_task)


def test_status_reflects_real_completed_job(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "inspect_document", lambda path: [{"page": 1, "type": "digital"}])

    def _fake_process_document(doc_id, path):
        tracker = progress.ProgressTracker(doc_id)
        tracker.init_pages([{"page": 1, "type": "digital"}])
        tracker.set_page_stage(1, "prescan", "running")
        tracker.set_page_stage(1, "prescan", "done")
        tracker.finish()

    monkeypatch.setattr(main, "process_document", _fake_process_document)

    (tmp_path / "fake.pdf").write_bytes(b"%PDF-1.4 fake")
    client.post("/process", json={"document_id": "doc1", "file_path": str(tmp_path / "fake.pdf")})

    status_response = client.get("/status/doc1")
    body = status_response.json()
    assert body["status"] == "completed"
    assert body["pages_total"] == 1
    assert body["pages"][0]["stages"]["prescan"] == "done"


def test_a_background_job_failure_is_recorded_not_silently_lost(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "inspect_document", lambda path: [{"page": 1, "type": "digital"}])

    def _fake_process_document(doc_id, path):
        tracker = progress.ProgressTracker(doc_id)
        tracker.init_pages([{"page": 1, "type": "digital"}])
        try:
            raise RuntimeError("simulated OCR crash")
        except Exception as exc:
            tracker.fail(str(exc))
            raise

    monkeypatch.setattr(main, "process_document", _fake_process_document)

    (tmp_path / "fake.pdf").write_bytes(b"%PDF-1.4 fake")
    client.post("/process", json={"document_id": "doc1", "file_path": str(tmp_path / "fake.pdf")})

    status_response = client.get("/status/doc1")
    body = status_response.json()
    assert body["status"] == "error"
    assert "simulated OCR crash" in body["error"]
