"use client";

const STEPS = ["Upload", "Process", "Results"];

export default function Stepper({ activeIndex }: { activeIndex: 0 | 1 | 2 }) {
  return (
    <div className="stepper">
      {STEPS.map((label, i) => (
        <div key={label} style={{ display: "contents" }}>
          <div className={`step${i < activeIndex ? " done" : i === activeIndex ? " active" : ""}`}>
            <div className="node">{i < activeIndex ? "✓" : i + 1}</div>
            <span className="label">{label}</span>
          </div>
          {i < STEPS.length - 1 && (
            <div className={`step-line${activeIndex >= i + 1 ? " filled" : ""}`} />
          )}
        </div>
      ))}
    </div>
  );
}
