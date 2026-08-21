"use client";

import { useState } from "react";

export type StepState = "done" | "active" | "pending" | "skip";

interface Step {
  label: string;
  subtitle: string;
  state: StepState;
}

interface StageGroup {
  name: string;
  steps: Step[];
}

const GROUP_NAMES = ["Pre-scan", "OCR", "Structure", "Decide"] as const;

function groupState(steps: Step[]): "done" | "active" | "pending" {
  const applicable = steps.filter((s) => s.state !== "skip");
  if (applicable.length === 0) return "pending";
  if (applicable.every((s) => s.state === "done")) return "done";
  if (applicable.some((s) => s.state === "active")) return "active";
  return "pending";
}

function StageIcon({ state }: { state: "done" | "active" | "pending" }) {
  return (
    <span className="stage-card-icon">
      {state === "done" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      )}
    </span>
  );
}

export default function StageCards({
  groups,
  elapsedSeconds,
}: {
  groups: [StageGroup, StageGroup, StageGroup, StageGroup];
  elapsedSeconds: number;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <div className="stage-cards">
      {groups.map((group, i) => {
        const state = groupState(group.steps);
        const isExpanded = expanded.has(i);
        const visibleSteps = group.steps.filter((s) => s.state !== "skip");
        return (
          <div className="stage-card" key={group.name} data-state={state}>
            <div className="stage-card-head">
              <StageIcon state={state} />
              <span className="stage-card-name">{group.name}</span>
            </div>
            {state === "active" && <span className="stage-card-time">{elapsedSeconds}s elapsed</span>}
            {state === "done" && <span className="stage-card-time">complete</span>}
            {visibleSteps.length > 0 && (
              <button type="button" className="stage-card-toggle" onClick={() => toggle(i)}>
                {isExpanded ? "Hide details ▲" : "Show details ▼"}
              </button>
            )}
            {isExpanded && (
              <div className="stage-card-detail step-timeline">
                {visibleSteps.map((step) => (
                  <div className="tl-row" key={step.label} data-state={step.state}>
                    <div className="tl-indicator">
                      <div className="tl-dot" />
                      <div className="tl-line" />
                    </div>
                    <div className="tl-content">
                      <div className="tl-title">{step.label}</div>
                      <div className="tl-subtitle">{step.subtitle}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export { GROUP_NAMES };
export type { Step, StageGroup };
