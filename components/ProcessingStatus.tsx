"use client";

import type { PageRegionsEntry } from "@/lib/types";

export type ProcessingPhase = "preparing" | "processing" | "done";

interface Stage {
  label: string;
  applicable: boolean;
}

function buildStages(hasDigital: boolean, hasScanned: boolean): Stage[] {
  return [
    { label: "Uploading document", applicable: true },
    { label: "Detecting PDF type", applicable: true },
    { label: "Extracting digital text — PyMuPDF", applicable: hasDigital },
    { label: "Detecting scanned layout — PP-StructureV3", applicable: hasScanned },
    { label: "Detecting BOQ table", applicable: hasScanned },
    { label: "Extracting printed values — PaddleOCR", applicable: hasScanned },
    { label: "Reading handwriting — Tesseract", applicable: hasScanned },
    { label: "Building BOQ structure", applicable: true },
    { label: "Running business rules", applicable: true },
    { label: "Resolving ambiguous values", applicable: true },
    { label: "Finalizing results", applicable: true },
  ];
}

// The backend runs /process as one synchronous call with no granular
// per-stage progress reporting. Known simplification (per spec): the first
// two stages complete during /api/prepare (before this view is even shown),
// every other applicable stage shows "active" together for the duration of
// the in-flight /api/process call, then all flip to "done" at once when it
// returns — rather than a truly step-by-step live trace.
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

export default function ProcessingStatus({
  fileName,
  pageImageUrl,
  pageIsScanned,
  hasDigital,
  hasScanned,
  digitalCount,
  scannedCount,
  phase,
  pageRegions,
}: {
  fileName: string;
  pageImageUrl: string;
  pageIsScanned: boolean;
  hasDigital: boolean;
  hasScanned: boolean;
  digitalCount: number;
  scannedCount: number;
  phase: ProcessingPhase;
  pageRegions: PageRegionsEntry | null;
}) {
  const stages = buildStages(hasDigital, hasScanned);
  const boxes = pageRegions ? normalizeRegions(pageRegions) : [];
  const legendKinds = Array.from(new Set(boxes.map((b) => b.kind)));

  const activeLabel =
    phase === "done"
      ? "Finalizing results…"
      : stages.find((s, i) => stageState(s, i, phase) === "active")?.label + "…" || "Uploading document…";

  return (
    <div className="proc-inner">
      <div className="proc-head">
        <h2>Processing SOW</h2>
        <span className="fname-sm">{fileName}</span>
      </div>
      <p className="route-summary">
        Pages routed: <b>{digitalCount}</b> digital · <b>{scannedCount}</b> scanned
      </p>

      <div className="proc-body">
        <div className="page-mock-wrap">
          <div className={`page-mock${pageIsScanned ? " scanned" : ""}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={pageImageUrl} alt="Document page 1" className="page-image" />
            {boxes.map((box) => (
              <div
                key={box.id}
                className={`region-box visible`}
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
                <div className="tl-content">{stage.label}</div>
              </div>
            ))}
          </div>
          <p className="proc-note">{activeLabel}</p>
        </div>
      </div>
    </div>
  );
}
