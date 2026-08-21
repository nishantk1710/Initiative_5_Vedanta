"use client";

import { useState } from "react";
import type { PrescanResult } from "@/lib/types";

function overallStatus(results: PrescanResult[]): "pass" | "warn" | "fail" {
  if (results.some((r) => r.status === "fail")) return "fail";
  if (results.some((r) => r.status === "warn")) return "warn";
  return "pass";
}

export default function QualityPanel({ prescan }: { prescan: PrescanResult[] }) {
  const [open, setOpen] = useState(false);
  if (prescan.length === 0) return null;

  const status = overallStatus(prescan);
  const flagged = prescan.filter((r) => r.status !== "pass");
  // Averaged across pages purely for the summary tile — the per-page detail
  // below still shows each page's own real numbers, never blended.
  const avg = (key: keyof PrescanResult) =>
    Math.round(prescan.reduce((sum, r) => sum + (r[key] as number), 0) / prescan.length);

  return (
    <div className="quality-panel">
      <button type="button" className={`quality-head${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)}>
        <span>Pre-scan quality</span>
        <span className={`pass-badge status-${status}`}>{status}</span>
        <span className="chev">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M6 9l6 6 6-6" />
          </svg>
        </span>
      </button>
      {open && (
        <div className="quality-body">
          {status === "pass" ? (
            <div className="quality-ok">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <circle cx="12" cy="12" r="10" />
                <path d="M8 12l3 3 5-6" />
              </svg>
              <div>
                <div className="t1">Quality looks good</div>
                <div className="t2">All {prescan.length} page(s) passed the pre-flight checks.</div>
              </div>
            </div>
          ) : (
            <div className="quality-warn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M12 9v4M12 17h.01M10.3 3.9L2.6 18a1 1 0 0 0 .9 1.5h17a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.7 0Z" />
              </svg>
              <div>
                <div className="t1">{flagged.length} of {prescan.length} page(s) flagged</div>
                <div className="t2">
                  {flagged
                    .flatMap((r) => r.reasons.map((reason) => `Page ${r.page}: ${reason}`))
                    .join(" · ") || "See per-page metrics below."}
                </div>
              </div>
            </div>
          )}
          <div className="metric-grid">
            <div className="metric">
              <div className="k">DPI</div>
              <div className="v">{prescan[0].dpi}</div>
            </div>
            <div className="metric">
              <div className="k">Avg. sharpness</div>
              <div className="v">{avg("sharpness")}</div>
            </div>
            <div className="metric">
              <div className="k">Avg. contrast</div>
              <div className="v">{avg("contrast")}</div>
            </div>
            <div className="metric">
              <div className="k">Avg. brightness</div>
              <div className="v">{avg("brightness")}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
