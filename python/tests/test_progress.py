"""Real per-stage progress + duration tracking (Phase 8, extended for the
stage-card UI's timing display) — every duration must be measured, never
fabricated."""

import time

import progress


def test_set_stage_records_previous_stage_as_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.set_stage("loading")
    tracker.set_stage("routing")
    assert tracker.completed == ["loading"]
    assert tracker._current == "routing"


def test_unknown_stage_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    try:
        tracker.set_stage("not_a_real_stage")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_finish_records_final_stage_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.set_stage("loading")
    tracker.finish()
    result = progress.read_progress("doc1")
    assert result["status"] == "completed"
    assert result["current_stage"] is None
    assert result["completed_stages"] == ["loading"]


def test_fail_preserves_completed_stages_and_records_error(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.set_stage("loading")
    tracker.set_stage("routing")
    tracker.fail("boom")
    result = progress.read_progress("doc1")
    assert result["status"] == "error"
    assert result["error"] == "boom"
    # routing was in-flight (never closed by set_stage/finish) when fail()
    # was called — fail() must not fabricate a completion for it.
    assert "routing" not in result["completed_stages"]
    assert "loading" in result["completed_stages"]


def test_durations_are_real_measured_time_not_fabricated(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.set_stage("loading")
    time.sleep(0.05)
    tracker.set_stage("routing")
    tracker.finish()
    result = progress.read_progress("doc1")
    assert result["stage_durations_ms"]["loading"] >= 40  # allow scheduler slack below the 50ms sleep
    assert "routing" in result["stage_durations_ms"]


def test_stage_never_marked_complete_before_set_stage_moves_past_it(tmp_path, monkeypatch):
    """A stage only gets a duration once something else starts — the
    currently-running stage must never appear in completed_stages while
    still in flight."""
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.set_stage("loading")
    result = progress.read_progress("doc1")
    assert result["current_stage"] == "loading"
    assert result["completed_stages"] == []
    assert result["stage_durations_ms"] == {}


def test_read_progress_returns_none_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    assert progress.read_progress("never-ran") is None


# --------------------------------------------------------------------------
# Per-page progress (async job model)
# --------------------------------------------------------------------------

def test_write_queued_is_readable_before_any_tracker_exists(tmp_path, monkeypatch):
    """The state a client polling GET /status sees immediately after
    POST /process, before the background job's own tracker has even
    constructed — must never 404."""
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    progress.write_queued("doc1", pages_total=3)
    result = progress.read_progress("doc1")
    assert result["status"] == "queued"
    assert result["pages_total"] == 3
    assert result["pages"] == []


def test_init_pages_sets_real_count_and_kind_never_hardcoded(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "digital"}, {"page": 2, "type": "scanned"}])
    result = progress.read_progress("doc1")
    assert result["pages_total"] == 2
    assert result["pages"][0] == {
        "page": 1, "status": "queued", "kind": "digital",
        "stages": {"prescan": "pending", "ocr": "pending", "structure": "pending", "decide": "pending"},
    }
    assert result["pages"][1]["kind"] == "scanned"


def test_set_page_stage_running_marks_page_active(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "scanned"}])
    tracker.set_page_stage(1, "ocr", "running")
    result = progress.read_progress("doc1")
    assert result["pages"][0]["status"] == "active"
    assert result["pages"][0]["stages"]["ocr"] == "running"
    assert result["live_page"] == 1


def test_page_only_marked_done_once_every_stage_group_is_done(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "scanned"}])
    for group in ("prescan", "ocr", "structure"):
        tracker.set_page_stage(1, group, "running")
        tracker.set_page_stage(1, group, "done")
    assert progress.read_progress("doc1")["pages"][0]["status"] == "active"  # decide still pending

    tracker.set_page_stage(1, "decide", "running")
    tracker.set_page_stage(1, "decide", "done")
    assert progress.read_progress("doc1")["pages"][0]["status"] == "done"


def test_set_stage_group_for_all_pages_updates_every_page_honestly(tmp_path, monkeypatch):
    """structure/decide genuinely run once over the whole document's
    evidence, not page by page — marking every page at once here reflects
    that real behavior, not a faked simultaneity."""
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "digital"}, {"page": 2, "type": "scanned"}])
    tracker.set_stage_group_for_all_pages("structure", "running")
    result = progress.read_progress("doc1")
    assert all(p["stages"]["structure"] == "running" for p in result["pages"])
    assert all(p["stages"]["ocr"] == "pending" for p in result["pages"])  # untouched


def test_live_page_is_the_lowest_active_page(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "scanned"}, {"page": 2, "type": "scanned"}])
    # page 1 fully done (every stage group), page 2 just started — only
    # page 2 should read as active/live.
    for group in progress.STAGE_GROUPS:
        tracker.set_page_stage(1, group, "running")
        tracker.set_page_stage(1, group, "done")
    tracker.set_page_stage(2, "ocr", "running")
    assert tracker.live_page == 2


def test_live_page_is_none_when_no_page_is_active(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "digital"}])
    assert tracker.live_page is None


def test_set_page_stage_rejects_unknown_page(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "digital"}])
    try:
        tracker.set_page_stage(99, "ocr", "running")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_set_page_stage_rejects_unknown_group():
    tracker = progress.ProgressTracker.__new__(progress.ProgressTracker)
    tracker.pages = {1: {"status": "queued", "stages": {}}}
    try:
        tracker.set_page_stage(1, "not_a_real_group", "running")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_finish_still_reports_completed_status_with_pages_present(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "document_dir", lambda doc_id: str(tmp_path))
    tracker = progress.ProgressTracker("doc1")
    tracker.init_pages([{"page": 1, "type": "digital"}])
    tracker.set_stage("loading")
    tracker.finish()
    result = progress.read_progress("doc1")
    assert result["status"] == "completed"
    assert result["pages_total"] == 1
