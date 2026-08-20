"use client";

import { useEffect, useState } from "react";
import type { PageRegionsEntry, PageRoute } from "@/lib/types";

export type ProcessingPhase = "preparing" | "processing" | "done";

interface Stage {
  label: string;
  subtitle: string;
  banner: string;
  applicable: boolean;
}

// `subtitle` is the always-visible, plain-language one-liner shown under
// every stage in the timeline (so a non-technical reader understands what
// each step means without recognizing jargon like "PP-StructureV3").
// `banner` is the punchier "what's happening right now" phrasing shown in
// the prominent stage-banner above the document panel while that stage is
// active — same idea, more headline-y tone.
function buildStages(hasDigital: boolean, hasScanned: boolean): Stage[] {
  return [
    {
      label: "Uploading document",
      subtitle: "Saving your file so it can be read",
      banner: "Saving your document",
      applicable: true,
    },
    {
      label: "Detecting PDF type",
      subtitle: "Checking if each page is text or a scan",
      banner: "Checking what kind of page this is",
      applicable: true,
    },
    {
      label: "Extracting digital text — PyMuPDF",
      subtitle: "Pulling text directly from the PDF",
      banner: "Now reading: text directly from the PDF",
      applicable: hasDigital,
    },
    {
      label: "Detecting scanned layout — PP-StructureV3",
      subtitle: "Finding tables, text blocks, and handwriting on the page",
      banner: "Now scanning: page layout for tables and text",
      applicable: hasScanned,
    },
    {
      label: "Detecting BOQ table",
      subtitle: "Locating the pricing table on the page",
      banner: "Now scanning: looking for the pricing table",
      applicable: hasScanned,
    },
    {
      label: "Extracting printed values — PaddleOCR",
      subtitle: "Reading printed numbers and text from the table",
      banner: "Now reading: printed table values (PaddleOCR)",
      applicable: hasScanned,
    },
    {
      label: "Reading handwriting — Tesseract",
      subtitle: "Reading handwritten notes and corrections",
      banner: "Now reading: handwritten notes (Tesseract)",
      applicable: hasScanned,
    },
    {
      label: "Building BOQ structure",
      subtitle: "Organizing everything into rows and columns",
      banner: "Now organizing: building the item list",
      applicable: true,
    },
    {
      label: "Running business rules",
      subtitle: "Checking the numbers add up correctly",
      banner: "Now checking: does the math add up",
      applicable: true,
    },
    {
      label: "Resolving ambiguous values",
      subtitle: "Double-checking anything unclear with AI",
      banner: "Now double-checking unclear values with AI",
      applicable: true,
    },
    {
      label: "Finalizing results",
      subtitle: "Putting together your final results",
      banner: "Now finishing: preparing your results",
      applicable: true,
    },
  ];
}

// The backend runs /process as one synchronous call with no granular
// per-stage progress reporting. Known simplification (per spec): the first
// two stages complete during /api/prepare (before this view is even shown),
// every other applicable stage shows "active" together for the duration of
// the in-flight /api/process call, then all flip to "done" at once when it
// returns. This timeline is GLOBAL — it reflects the whole document's
// pipeline status and never changes when the user pages through the
// document panel below.
function stageState(stage: Stage, index: number, phase: ProcessingPhase): "done" | "active" | "pending" | "skip" {
  if (!stage.applicable) return "skip";
  if (phase === "done") return "done";
  if (phase === "processing") return index < 2 ? "done" : "active";
  return index === 0 ? "active" : "pending";
}

type RegionKind = "table" | "handwriting" | "digital";

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
    const kind: RegionKind = category === "handwriting" ? "handwriting" : "table";
    const label = kind === "handwriting" ? "Handwriting" : region.type === "table" ? "BOQ Table" : "Printed text";
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

// A page is worth flagging as "has content" once we know it either has
// detected table/handwriting regions (scanned) or simply hasn't been
// determined yet (still processing — shown as a pending amber dot rather
// than silently looking identical to "nothing here").
function pillState(page: PageRoute, entry: PageRegionsEntry | undefined): "has-content" | "pending" | "none" {
  if (page.type === "digital") return "none";
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
  hasDigital,
  hasScanned,
  digitalCount,
  scannedCount,
  phase,
  startedAt,
}: {
  documentId: string;
  fileName: string;
  pages: PageRoute[];
  currentPage: number;
  onPageChange: (page: number) => void;
  regionsByPage: Map<number, PageRegionsEntry>;
  hasDigital: boolean;
  hasScanned: boolean;
  digitalCount: number;
  scannedCount: number;
  phase: ProcessingPhase;
  startedAt: number | null;
}) {
  const stages = buildStages(hasDigital, hasScanned);
  const applicableStages = stages.filter((s) => s.applicable);
  const activeIndex = stages.findIndex((s, i) => stageState(s, i, phase) === "active");
  const activeStage = activeIndex >= 0 ? stages[activeIndex] : null;

  const doneCount = applicableStages.filter((s, i) => stageState(s, stages.indexOf(s), phase) === "done").length;
  const stepNumber = phase === "done" ? applicableStages.length : doneCount + (activeStage ? 1 : 0);
  const progressPct = applicableStages.length > 0 ? (stepNumber / applicableStages.length) * 100 : 0;

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

  // Nothing to show ON the document yet for this page (still mid-stage,
  // hasn't reached region detection, or this specific page's regions
  // aren't in yet) — keep the panel visibly "alive" instead of static.
  const showAliveAnimation = phase === "processing" && boxes.length === 0;

  const bannerText = phase === "done" ? "All done — results ready" : activeStage?.banner ?? "Getting started…";

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
            Step {Math.min(stepNumber, applicableStages.length)} of {applicableStages.length}
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
                const state = pillState(page, regionsByPage.get(page.page));
                return (
                  <button
                    key={page.page}
                    type="button"
                    className={`page-pill${page.page === currentPage ? " active" : ""}${state !== "none" ? ` ${state}` : ""}`}
                    onClick={() => onPageChange(page.page)}
                    title={
                      state === "has-content"
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
          <div className="step-timeline">
            {stages.map((stage, i) => (
              <div className="tl-row" key={stage.label} data-state={stageState(stage, i, phase)}>
                <div className="tl-indicator">
                  <div className="tl-dot" />
                  <div className="tl-line" />
                </div>
                <div className="tl-content">
                  <div className="tl-title">{stage.label}</div>
                  <div className="tl-subtitle">{stage.subtitle}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
