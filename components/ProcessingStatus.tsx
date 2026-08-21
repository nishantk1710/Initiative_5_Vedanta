"use client";

import { useEffect, useState } from "react";
import type { PageRegionsEntry, PageRoute, ProcessingProgress, StageGroupName, StageGroupState } from "@/lib/types";
import StageCards, { type StageGroup, type Step, type StepState } from "@/components/StageCards";

export type ProcessingPhase = "preparing" | "processing" | "done";

const GROUP_ORDER: StageGroupName[] = ["prescan", "ocr", "structure", "decide"];

// Descriptive subtitles for each group — informational copy only, never a
// source of truth for state (that always comes from `progress`).
const GROUP_INFO: Record<StageGroupName, { name: string; subtitle: string }> = {
  prescan: { name: "Pre-scan", subtitle: "Rendering the page and checking scan quality" },
  ocr: { name: "OCR", subtitle: "Detecting layout and reading text/handwriting" },
  structure: { name: "Structure", subtitle: "Classifying the document and building its structure" },
  decide: { name: "Decide", subtitle: "Validating values and finalizing results" },
};

function realGroupState(state: StageGroupState | undefined): StepState {
  if (state === "running") return "active";
  if (state === "done") return "done";
  return "pending";
}

type RegionKind = "table" | "handwriting" | "digital" | "llm";

interface RegionBox {
  id: string;
  kind: RegionKind;
  label: string;
  top: number;
  left: number;
  width: number;
  height: number;
}

const LEGEND: Record<RegionKind, { label: string; color: string }> = {
  table: { label: "Printed — PaddleOCR", color: "var(--blue-500)" },
  handwriting: { label: "Handwritten — Tesseract", color: "var(--core-amber)" },
  digital: { label: "Extracted — PyMuPDF", color: "var(--pymupdf)" },
  llm: { label: "AI-identified from text", color: "var(--blue-900)" },
};

function truncate(text: string, max = 24): string {
  const trimmed = text.trim();
  return trimmed.length > max ? trimmed.slice(0, max - 1) + "…" : trimmed;
}

function normalizeRegions(entry: PageRegionsEntry): RegionBox[] {
  const { width, height } = entry;
  if (!width || !height) return [];

  if (entry.type === "digital") {
    return entry.regions.map((block, i) => {
      const bbox = block.bbox as [number, number, number, number];
      const value = String(block.value ?? "");
      return {
        id: `d-${i}`,
        kind: "digital",
        label: truncate(value),
        left: (bbox[0] / width) * 100,
        top: (bbox[1] / height) * 100,
        width: ((bbox[2] - bbox[0]) / width) * 100,
        height: ((bbox[3] - bbox[1]) / height) * 100,
      };
    });
  }

  return entry.regions.map((region, i) => {
    const bbox = region.bbox as [number, number, number, number];
    const category = String(region.category ?? "");
    const kind: RegionKind =
      category === "handwriting" ? "handwriting" : category === "llm_line_item" ? "llm" : "table";
    const label =
      kind === "handwriting"
        ? "Handwriting"
        : kind === "llm"
          ? `AI: ${truncate(String(region.content ?? "Line item"), 18)}`
          : region.type === "table"
            ? "BOQ Table"
            : "Printed text";
    return {
      id: `s-${i}`,
      kind,
      label,
      left: (bbox[0] / width) * 100,
      top: (bbox[1] / height) * 100,
      width: ((bbox[2] - bbox[0]) / width) * 100,
      height: ((bbox[3] - bbox[1]) / height) * 100,
    };
  });
}

// A page's real state comes from progress.pages[i].status when we have it
// (queued/active/done, from python/progress.py) — falls back to the
// region-presence heuristic only before any progress has been polled yet.
function pillState(
  page: PageRoute,
  entry: PageRegionsEntry | undefined,
  pageProgressStatus: "queued" | "active" | "done" | undefined,
): "has-content" | "pending" | "none" {
  if (page.type === "digital") return "none";
  if (pageProgressStatus === "done") return entry && entry.regions.length > 0 ? "has-content" : "none";
  if (pageProgressStatus === "active" || pageProgressStatus === "queued") return "pending";
  if (!entry) return "pending";
  return entry.regions.length > 0 ? "has-content" : "none";
}

export default function ProcessingStatus({
  documentId,
  fileName,
  pages,
  currentPage,
  onPageChange,
  regionsByPage,
  digitalCount,
  scannedCount,
  phase,
  startedAt,
  progress,
}: {
  documentId: string;
  fileName: string;
  pages: PageRoute[];
  currentPage: number;
  onPageChange: (page: number) => void;
  regionsByPage: Map<number, PageRegionsEntry>;
  digitalCount: number;
  scannedCount: number;
  phase: ProcessingPhase;
  startedAt: number | null;
  // Real, polled per-page progress (python/progress.py via GET /status) —
  // null before the first poll response arrives. Every stage/page state
  // shown below comes from this, never simulated with a timer.
  progress: ProcessingProgress | null;
}) {
  const pagesTotal = progress?.pages_total ?? pages.length;
  const livePage = progress?.live_page ?? null;
  const currentPageProgress = progress?.pages.find((p) => p.page === currentPage) ?? null;

  const stageGroups = GROUP_ORDER.map((groupKey): StageGroup => {
    const info = GROUP_INFO[groupKey];
    const state: StepState =
      phase === "done" ? "done" : realGroupState(currentPageProgress?.stages[groupKey]);
    const steps: Step[] = [{ label: info.name, subtitle: info.subtitle, state }];
    return { name: info.name, steps };
  }) as [StageGroup, StageGroup, StageGroup, StageGroup];

  const pagesDone = progress?.pages.filter((p) => p.status === "done").length ?? 0;
  const progressPct = pagesTotal > 0 ? (phase === "done" ? 100 : (pagesDone / pagesTotal) * 100) : 0;

  const activeGroupKey = GROUP_ORDER.find((g) => currentPageProgress?.stages[g] === "running");
  const bannerText =
    phase === "done"
      ? "All done — results ready"
      : phase === "preparing"
        ? "Saving your document"
        : livePage
          ? `Processing page ${livePage} of ${pagesTotal}${activeGroupKey ? ` — ${GROUP_INFO[activeGroupKey].subtitle.toLowerCase()}` : ""}`
          : "Getting started…";

  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    if (phase !== "processing" || startedAt === null) return;
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [phase, startedAt]);

  const pageEntry = regionsByPage.get(currentPage) ?? null;
  const pageRoute = pages.find((p) => p.page === currentPage);
  const pageIsScanned = pageRoute?.type === "scanned";
  const boxes = pageEntry ? normalizeRegions(pageEntry) : [];
  const legendKinds = Array.from(new Set(boxes.map((b) => b.kind)));
  const pageImageUrl = `/api/result/${documentId}/page/${currentPage}`;

  const showAliveAnimation = phase === "processing" && boxes.length === 0;

  return (
    <div className="proc-inner">
      <div className="proc-head">
        <h2>Processing SOW</h2>
        <span className="fname-sm">{fileName}</span>
      </div>
      <p className="route-summary">
        Pages routed: <b>{digitalCount}</b> digital · <b>{scannedCount}</b> scanned
      </p>

      <div className="overall-progress">
        <div className="bar-label">
          <span>
            {phase === "done" ? `${pagesTotal} of ${pagesTotal} pages` : `${pagesDone} of ${pagesTotal} pages done`}
          </span>
          <span>{phase === "done" ? "Complete" : `${Math.round(progressPct)}%`}</span>
        </div>
        <div className="bar-track">
          <div className="bar-fill" style={{ width: `${progressPct}%` }} />
        </div>
      </div>

      <div className={`stage-banner${phase === "done" ? " is-done" : ""}`}>
        <span className="banner-dot" />
        <span className="banner-text">{bannerText}</span>
        {phase === "processing" && elapsedSeconds >= 4 && (
          <span className="banner-elapsed">started {elapsedSeconds}s ago</span>
        )}
      </div>

      <div className="proc-body">
        <div className="page-mock-wrap">
          <div className={`page-mock${pageIsScanned ? " scanned" : ""}${showAliveAnimation ? " processing-pulse" : ""}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={pageImageUrl} alt={`Document page ${currentPage}`} className="page-image" />
            {showAliveAnimation && <div className="scan-sweep" />}
            {boxes.map((box) => (
              <div
                key={box.id}
                className="region-box visible"
                data-kind={box.kind}
                data-state={phase === "done" ? "done" : "active"}
                style={{
                  top: `${box.top}%`,
                  left: `${box.left}%`,
                  width: `${box.width}%`,
                  height: `${box.height}%`,
                }}
              >
                <span className="region-label">{box.label}</span>
              </div>
            ))}
          </div>

          {pages.length > 1 && (
            <div className="page-nav">
              <button
                type="button"
                className="page-nav-btn"
                disabled={currentPage <= pages[0].page}
                onClick={() => onPageChange(currentPage - 1)}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                  <path d="M15 18l-6-6 6-6" />
                </svg>
                Prev
              </button>
              <span className="page-nav-label">
                Page {currentPage} of {pages.length}
              </span>
              <button
                type="button"
                className="page-nav-btn"
                disabled={currentPage >= pages[pages.length - 1].page}
                onClick={() => onPageChange(currentPage + 1)}
              >
                Next
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                  <path d="M9 18l6-6-6-6" />
                </svg>
              </button>
            </div>
          )}

          {pages.length > 1 && (
            <div className="page-pills">
              {pages.map((page) => {
                const pageProgressStatus = progress?.pages.find((p) => p.page === page.page)?.status;
                const state = pillState(page, regionsByPage.get(page.page), pageProgressStatus);
                return (
                  <button
                    key={page.page}
                    type="button"
                    className={`page-pill${page.page === currentPage ? " active" : ""}${state !== "none" ? ` ${state}` : ""}${page.page === livePage ? " live" : ""}`}
                    onClick={() => onPageChange(page.page)}
                    title={
                      page.page === livePage
                        ? "Currently being processed"
                        : state === "has-content"
                          ? "Detected table/handwriting region"
                          : state === "pending"
                            ? "Still processing"
                            : "Digital text only"
                    }
                  >
                    <span className="pdot" />
                    {page.page}
                  </button>
                );
              })}
            </div>
          )}

          <div className="doc-legend">
            {legendKinds.map((kind) => (
              <span className="item" key={kind}>
                <span
                  className="swatch"
                  style={{ borderColor: LEGEND[kind].color, background: `${LEGEND[kind].color}22` }}
                />
                {LEGEND[kind].label}
              </span>
            ))}
          </div>
        </div>

        <div>
          <StageCards groups={stageGroups} elapsedSeconds={elapsedSeconds} />
        </div>
      </div>
    </div>
  );
}
