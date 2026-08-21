"use client";

import type { PipelineStage, ProcessingProgress } from "@/lib/types";

// Maps python/progress.py's real 11 pipeline stages onto the 4 named cards
// from the reference design. Only stages that actually ran for this
// document contribute to a card's total — e.g. handwriting_ocr never runs
// for an all-digital PDF, so it simply isn't in stage_durations_ms and
// contributes nothing (never a fabricated 0ms placeholder).
const STAGE_GROUPS: { name: string; stages: PipelineStage[]; icon: string }[] = [
  {
    name: "Pre-scan",
    stages: ["loading", "routing", "rendering", "prescan"],
    icon: "M3 7V5a2 2 0 0 1 2-2h2M3 17v2a2 2 0 0 0 2 2h2M21 7V5a2 2 0 0 0-2-2h-2M21 17v2a2 2 0 0 1-2 2h-2M3 12h18",
  },
  {
    name: "OCR",
    stages: ["layout_detection", "ocr", "handwriting_ocr"],
    icon: "M12 12m-3 0a3 3 0 106 0 3 3 0 10-6 0M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z",
  },
  {
    name: "Structure",
    stages: ["document_understanding", "schema_discovery", "semantic_extraction"],
    icon: "M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4L12 3Z",
  },
  {
    name: "Decide",
    stages: ["validation", "finalization"],
    icon: "M14.5 3l-9 9 2 5 5 2 9-9-7-7ZM9 15l-5 5",
  },
];

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

export default function FinalStageRow({ progress }: { progress: ProcessingProgress | null }) {
  const durations = progress?.stage_durations_ms ?? {};

  return (
    <div className="stage-row">
      {STAGE_GROUPS.map((group, i) => {
        const ran = group.stages.filter((s) => s in durations);
        const totalMs = ran.reduce((sum, s) => sum + (durations[s] ?? 0), 0);
        const didRun = ran.length > 0;
        return (
          <div className="stage-row-item" key={group.name}>
            <div className="stage-card" data-state={didRun ? "done" : "skip"}>
              <div className="icon-box">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                  <path d={group.icon} />
                </svg>
              </div>
              <div className="txt">
                <div className="label">
                  {group.name}
                  {didRun && (
                    <svg className="check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                      <path d="M20 6L9 17l-4-4" />
                    </svg>
                  )}
                </div>
                <div className="time mono">{didRun ? formatMs(totalMs) : "skipped"}</div>
              </div>
            </div>
            {i < STAGE_GROUPS.length - 1 && (
              <div className="stage-connector">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
