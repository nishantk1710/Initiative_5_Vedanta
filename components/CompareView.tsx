"use client";

import { useEffect, useState } from "react";
import type { CompareResult, EngineInfo, PageRoute } from "@/lib/types";

async function fetchComparison(documentId: string, page: number, engineIds: string[]): Promise<CompareResult> {
  const query = engineIds.length > 0 ? `?engines=${engineIds.join(",")}` : "";
  const res = await fetch(`/api/compare/${documentId}/${page}${query}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Comparison failed (${res.status})`);
  }
  return res.json() as Promise<CompareResult>;
}

export default function CompareView({ documentId, pages }: { documentId: string; pages: PageRoute[] }) {
  const scannedPages = pages.filter((p) => p.type === "scanned");
  const defaultPage = scannedPages[0]?.page ?? pages[0]?.page ?? 1;

  const [page, setPage] = useState(defaultPage);
  const [engines, setEngines] = useState<EngineInfo[] | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The engine list comes from the backend (GET /api/engines), so adding a
  // third engine later is a backend config change — this component never
  // hardcodes an engine's id, display name, or whether it reports
  // confidence.
  useEffect(() => {
    fetch("/api/engines")
      .then((r) => (r.ok ? (r.json() as Promise<{ engines: EngineInfo[] }>) : Promise.reject(new Error("engines"))))
      .then((data) => setEngines(data.engines))
      .catch(() => setEngines([]));
  }, []);

  const engineById = new Map((engines ?? []).map((e) => [e.id, e]));
  const comparableEngines = (engines ?? []).filter((e) => e.available);

  async function runComparison() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchComparison(documentId, page, comparableEngines.map((e) => e.id));
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="compare-view">
      <div className="compare-controls">
        <label htmlFor="compare-page-select">Page</label>
        <select id="compare-page-select" value={page} onChange={(e) => setPage(Number(e.target.value))}>
          {pages.map((p) => (
            <option key={p.page} value={p.page}>
              Page {p.page} ({p.type})
            </option>
          ))}
        </select>
        <button
          type="button"
          className="process-btn compare-run-btn"
          onClick={runComparison}
          disabled={loading || comparableEngines.length === 0}
        >
          {loading ? "Running…" : result ? "Re-run" : "Run comparison"}
        </button>
      </div>

      {error && <p style={{ color: "var(--hazard-rust)", fontSize: 13 }}>{error}</p>}

      {engines !== null && comparableEngines.length === 0 && (
        <p className="compare-hint">No OCR engines are currently available to compare.</p>
      )}

      {!error && !result && !loading && comparableEngines.length > 0 && (
        <p className="compare-hint">
          Runs {comparableEngines.map((e) => e.name).join(" and ")} against the same rendered page and shows their raw
          output side by side — useful for judging which engine handles a specific document better.
        </p>
      )}

      {result && (
        <div className="compare-columns">
          {result.results.map((entry) => {
            const info = engineById.get(entry.engine);
            return (
              <div className="compare-column" key={entry.engine}>
                <div className="compare-column-head">
                  <span className="compare-engine-name">{info?.name ?? entry.engine}</span>
                  {entry.available && <span className="compare-latency">{entry.latency_ms.toFixed(0)} ms</span>}
                </div>

                {!entry.available && <p className="compare-unavailable">Unavailable — {entry.reason}</p>}

                {entry.available && (
                  <>
                    <div className="compare-stats">
                      <span>{entry.value_count} values detected</span>
                      <span>
                        {/* Whether a confidence number is expected at all is
                            the ENGINE's documented capability (from
                            /api/engines), not a guess from its id string —
                            entry.confidence_available then reports whether
                            this particular run actually produced one. */}
                        {info?.exposes_confidence === false
                          ? "this engine does not report per-value confidence"
                          : entry.confidence_available && entry.average_confidence !== null
                            ? `${Math.round(entry.average_confidence * 100)}% avg confidence`
                            : "confidence not available for this run"}
                      </span>
                    </div>
                    <pre className="compare-text">{entry.text || "(no text detected)"}</pre>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
