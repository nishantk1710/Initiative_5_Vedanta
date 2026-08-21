"use client";

import { useEffect, useState } from "react";
import type { CompareResult, EngineInfo, PageRegionsEntry } from "@/lib/types";

// Digital pages already have their real text in regions.json (PyMuPDF
// spans) — no OCR involved, so it's shown directly with no engine choice.
// Scanned pages have no raw full-page text persisted anywhere (only the
// structured line items/metadata that came out of it), so this fetches it
// live from /api/compare — a real OCR call, not a cached fabrication —
// which is also why the engine choice only applies to scanned pages.
export default function OcrTextTab({
  documentId,
  page,
  engineId,
  engines,
}: {
  documentId: string;
  page: PageRegionsEntry;
  engineId: string | null;
  // From GET /api/engines — this component never hardcodes an engine's
  // name or whether it reports confidence.
  engines: EngineInfo[];
}) {
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDigital = page.type === "digital";
  const engineInfo = engines.find((e) => e.id === engineId) ?? null;

  useEffect(() => {
    if (isDigital || !engineId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/compare/${documentId}/${page.page}?engines=${engineId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`OCR failed (${r.status})`);
        return r.json() as Promise<CompareResult>;
      })
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "OCR failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, page.page, engineId, isDigital]);

  if (isDigital) {
    const text = page.regions
      .map((r) => String(r.value ?? ""))
      .filter(Boolean)
      .join("\n");
    return (
      <>
        <div className="badge-row">
          <span className="badge engine">pymupdf</span>
          <span className="badge">digital text</span>
        </div>
        <pre className="ocr-text">{text || "(no text on this page)"}</pre>
      </>
    );
  }

  if (!engineId) {
    return <div className="empty-tab">No OCR engine available</div>;
  }
  if (loading) {
    return <div className="empty-tab">Reading page text…</div>;
  }
  if (error) {
    return <p style={{ color: "var(--hazard-rust)", fontSize: 13 }}>{error}</p>;
  }
  const entry = result?.results[0];
  if (!entry) {
    return <div className="empty-tab">No OCR result yet</div>;
  }

  const engineLabel = engineInfo?.name ?? entry.engine;

  if (!entry.available) {
    return <p className="compare-unavailable">{engineLabel} unavailable — {entry.reason}</p>;
  }

  // Whether confidence is expected at all is the engine's documented
  // capability from /api/engines — never inferred from its id string, so a
  // new engine added backend-side gets the right treatment automatically.
  const expectsConfidence = engineInfo?.exposes_confidence !== false;
  const hasConfidence = expectsConfidence && entry.confidence_available && entry.average_confidence !== null;

  return (
    <>
      <div className="badge-row">
        <span className="badge engine">{engineLabel}</span>
        <span className="badge">{entry.latency_ms.toFixed(0)} ms</span>
        <span className="badge">{entry.value_count} values</span>
        {hasConfidence ? (
          <span className="badge pct">conf {Math.round(entry.average_confidence! * 100)}%</span>
        ) : (
          <span className="badge warn">no per-value confidence</span>
        )}
      </div>
      {!hasConfidence && (
        <div className="warn-banner">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M12 9v4M12 17h.01M10.3 3.9L2.6 18a1 1 0 0 0 .9 1.5h17a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.7 0Z" />
          </svg>
          {expectsConfidence
            ? `${engineLabel} did not report per-value confidence for this page.`
            : `${engineLabel} does not expose per-value OCR confidence.`}
        </div>
      )}
      <pre className="ocr-text">{entry.text || "(no text detected)"}</pre>
    </>
  );
}
