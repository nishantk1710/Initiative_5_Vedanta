"""File-based per-page + per-stage progress tracking for async /process
jobs.

Written to results/<id>/progress.json DURING the background pipeline run —
no new infra (no Redis, no job queue, no background worker beyond a single
FastAPI BackgroundTask). GET /status/<id> reads this file so the frontend
can show which PAGE is genuinely being worked on right now, and which named
stage group that page has reached, instead of the previous "every
applicable stage shows active for the whole call, then all flip to done at
once" approximation.

Two kinds of stage genuinely exist in this pipeline, and this tracker
reports each honestly rather than forcing one shape onto both:
  - Pre-scan and OCR/layout-detection genuinely run ONE PAGE AT A TIME
    (see pipeline.py's per-page loop) — set_page_stage() reports exactly
    that page's real state.
  - Structure (document understanding / schema discovery / semantic
    extraction) and Decide (validation / finalization) genuinely operate
    on EVERY page's evidence AT ONCE in a single pass — that is not a
    simplification or a faked simultaneity, it is what those functions
    actually do, so set_stage_group_for_all_pages() reports that honestly
    too, once each, at the moment that whole-document work starts/ends.

A page/stage is only ever recorded as running/done after that work
genuinely started/finished — never faked or pre-emptively marked for a
page not yet reached.

Known limitation, acceptable for now: this is an in-memory-during-the-call,
file-backed tracker for a single-process/single-worker deployment. It does
not survive a service restart mid-job, and does not coordinate across
multiple worker processes. Fine for the current deployment; would need a
real job store (DB row, Redis, etc.) to scale past one worker.
"""

import json
import os
import time

from paths import document_dir

# Whole-document named stages — unchanged from the original tracker, kept
# for the per-stage duration timings the results page's stage-summary UI
# already reads (stage_durations_ms). A stage that doesn't apply to a given
# document (e.g. handwriting_ocr for an all-digital PDF) is simply never
# written.
STAGES = (
    "loading",
    "routing",
    "rendering",
    "prescan",
    "layout_detection",
    "ocr",
    "handwriting_ocr",
    "document_understanding",
    "schema_discovery",
    "semantic_extraction",
    "validation",
    "finalization",
)

# The 4 named groups the frontend actually shows per page — see
# pipeline.py's callers of set_page_stage()/set_stage_group_for_all_pages()
# for exactly which STAGES entry maps to which group; kept as an explicit
# call-site decision there rather than an implicit table here, since
# set_stage() (whole-document duration tracking) and the per-page methods
# are deliberately independent — set_stage() has no page context to derive
# a per-page transition from.
STAGE_GROUPS = ("prescan", "ocr", "structure", "decide")


def _progress_path(document_id: str) -> str:
    return os.path.join(document_dir(document_id), "progress.json")


def _write(document_id: str, data: dict) -> None:
    path = _progress_path(document_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + f".{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)  # atomic on both POSIX and Windows — no reader ever sees a half-written file


def write_queued(document_id: str, pages_total: int) -> None:
    """Written synchronously by the /process endpoint BEFORE the background
    task is dispatched, so a client that polls GET /status immediately
    after the POST /process response never sees a 404 — there's a real,
    if momentary, "queued" state on disk until the background
    ProgressTracker takes over and overwrites it with "processing"."""
    _write(
        document_id,
        {
            "job_id": document_id,
            "status": "queued",
            "pages_total": pages_total,
            "pages": [],
            "live_page": None,
            "current_stage": None,
            "completed_stages": [],
            "stage_durations_ms": {},
        },
    )


class ProgressTracker:
    """One instance per /process job. init_pages() must be called once,
    with the REAL page list from inspect_document(), before any per-page
    update. set_stage(name) tracks whole-document named-stage durations
    (unchanged contract); set_page_stage()/set_stage_group_for_all_pages()
    track the per-page state the frontend actually renders. finish()/fail()
    close out the run."""

    def __init__(self, document_id: str):
        self.document_id = document_id
        self.completed: list[str] = []
        # Wall-clock duration of each completed named stage, measured with
        # time.monotonic() — real elapsed time, never a fabricated number.
        self.durations_ms: dict[str, float] = {}
        self._current: str | None = None
        self._current_started_at: float | None = None
        self.pages_total = 0
        self.pages: dict[int, dict] = {}
        self._flush()

    def init_pages(self, pages: list[dict]) -> None:
        """pages: [{"page": N, "type": "digital"|"scanned"}, ...] — the
        REAL page list from inspect_document(), never hardcoded or
        estimated. Must be called exactly once, before any per-page stage
        update; pages_total and the pages[] list are derived entirely from
        this."""
        self.pages_total = len(pages)
        self.pages = {
            p["page"]: {
                "page": p["page"],
                "status": "queued",
                "kind": p["type"],
                "stages": {group: "pending" for group in STAGE_GROUPS},
            }
            for p in pages
        }
        self._flush()

    def set_page_stage(self, page_number: int, stage_group: str, state: str) -> None:
        """state: "running" or "done", for exactly the page/stage-group
        that genuinely just started/finished — never called ahead of the
        real work. Raises if init_pages() hasn't run or page_number/
        stage_group aren't real, rather than silently no-op'ing on a typo."""
        if stage_group not in STAGE_GROUPS:
            raise ValueError(f"unknown stage group: {stage_group!r}")
        if page_number not in self.pages:
            raise ValueError(f"page {page_number} was not in init_pages()'s page list")
        if state not in ("running", "done"):
            raise ValueError(f"unknown page stage state: {state!r}")

        page_state = self.pages[page_number]
        page_state["stages"][stage_group] = state
        if state == "running":
            page_state["status"] = "active"
        elif all(s == "done" for s in page_state["stages"].values()):
            page_state["status"] = "done"
        self._flush()

    def set_stage_group_for_all_pages(self, stage_group: str, state: str) -> None:
        """For structure/decide: stages that genuinely run once over every
        page's evidence together, not page by page. Marking every page's
        stage_group this way is an honest reflection of that — not the
        "fake simultaneity" this tracker exists to avoid, since these
        stages truly do apply to the whole document at once."""
        for page_number in self.pages:
            self.set_page_stage(page_number, stage_group, state)

    def set_stage(self, stage: str) -> None:
        """Whole-document named-stage duration tracking (unchanged
        contract, independent of the per-page state below)."""
        if stage not in STAGES:
            raise ValueError(f"unknown progress stage: {stage!r}")
        self._close_current_stage()
        self._current = stage
        self._current_started_at = time.monotonic()
        self._flush()

    @property
    def live_page(self) -> int | None:
        for page_number in sorted(self.pages):
            if self.pages[page_number]["status"] == "active":
                return page_number
        return None

    def _flush(self, status: str = "processing", error: str | None = None) -> None:
        payload = {
            "job_id": self.document_id,
            "status": status,
            "current_stage": self._current,
            "completed_stages": list(self.completed),
            "stage_durations_ms": dict(self.durations_ms),
            "pages_total": self.pages_total,
            "pages": [self.pages[p] for p in sorted(self.pages)],
            "live_page": self.live_page,
        }
        if error is not None:
            payload["error"] = error
        _write(self.document_id, payload)

    def _close_current_stage(self) -> None:
        if self._current is None:
            return
        elapsed_ms = (time.monotonic() - self._current_started_at) * 1000
        self.durations_ms[self._current] = round(elapsed_ms, 1)
        self.completed.append(self._current)

    def finish(self) -> None:
        self._close_current_stage()
        self._current = None
        self._flush(status="completed")

    def fail(self, message: str) -> None:
        self._flush(status="error", error=message)


def read_progress(document_id: str) -> dict | None:
    path = _progress_path(document_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
