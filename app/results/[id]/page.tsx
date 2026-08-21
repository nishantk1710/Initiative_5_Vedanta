"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Stepper from "@/components/Stepper";
import BOQTable from "@/components/BOQTable";
import StructuredFieldList from "@/components/StructuredFieldList";
import PageHighlightViewer, { type Highlight } from "@/components/PageHighlightViewer";
import CompareView from "@/components/CompareView";
import FinalStageRow from "@/components/FinalStageRow";
import QualityPanel from "@/components/QualityPanel";
import OcrTextTab from "@/components/OcrTextTab";
import DecisionTab from "@/components/DecisionTab";
import AllResultsTab from "@/components/AllResultsTab";
import PageStrip from "@/components/PageStrip";
import type { DocumentType, EngineInfo, PageRegionsEntry, PageRoute, ProcessResult, ProcessingProgress } from "@/lib/types";

// Known types get a friendly label; anything else (a document type
// classifier.py identifies that the UI hasn't been specifically taught
// about yet) still renders sensibly instead of crashing on a missing key.
const KNOWN_CASE_TAG_LABEL: Partial<Record<DocumentType, string>> = {
  invoice: "Invoice",
  boq: "Mining SOW",
  bank_statement: "Bank Statement",
  resume: "Resume",
  contract: "Contract",
  purchase_order: "Purchase Order",
  receipt: "Receipt",
  unknown: "Unrecognized document",
};

const KNOWN_RESULT_TITLE: Partial<Record<DocumentType, string>> = {
  invoice: "Invoice Result",
  boq: "Mining SOW Result",
  bank_statement: "Bank Statement Result",
  resume: "Resume Result",
  contract: "Contract Result",
  purchase_order: "Purchase Order Result",
  receipt: "Receipt Result",
  unknown: "Document Result",
};

type ResultTab = "ocr" | "structured" | "decision" | "compare" | "allresults";

function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

function caseTagLabel(type: DocumentType): string {
  return KNOWN_CASE_TAG_LABEL[type] ?? titleCase(String(type));
}

function resultTitle(type: DocumentType): string {
  return KNOWN_RESULT_TITLE[type] ?? `${titleCase(String(type))} Result`;
}

export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [result, setResult] = useState<ProcessResult | null>(null);
  const [pages, setPages] = useState<PageRegionsEntry[] | null>(null);
  const [progress, setProgress] = useState<ProcessingProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<ResultTab>("ocr");
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [viewedPage, setViewedPage] = useState(1);
  // Engine list comes from the backend (GET /api/engines) — never hardcoded
  // here, so adding an engine is a backend config change. Only the OCR-text
  // tab actually re-runs anything per engine; Structured/Decision reflect
  // the one real extraction run (deterministic geometry + the classic OCR
  // path), so an engine toggle there wouldn't mean anything.
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [ocrEngineId, setOcrEngineId] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch(`/api/result/${id}`).then((r) => {
        if (!r.ok) throw new Error(`No result found for ${id}`);
        return r.json() as Promise<ProcessResult>;
      }),
      fetch(`/api/result/${id}/pages`).then((r) => (r.ok ? (r.json() as Promise<PageRegionsEntry[]>) : [])),
      fetch(`/api/status/${id}`).then((r) => (r.ok ? (r.json() as Promise<ProcessingProgress>) : null)),
    ])
      .then(([resultData, pagesData, progressData]) => {
        setResult(resultData);
        setPages(pagesData);
        setProgress(progressData);
        setViewedPage(pagesData[0]?.page ?? 1);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load result"));
  }, [id]);

  useEffect(() => {
    fetch("/api/engines")
      .then((r) => (r.ok ? (r.json() as Promise<{ engines: EngineInfo[] }>) : Promise.reject(new Error("engines"))))
      .then((data) => {
        setEngines(data.engines);
        // Default to the first AVAILABLE engine the backend reports, rather
        // than assuming a particular engine id exists.
        setOcrEngineId(data.engines.find((e) => e.available)?.id ?? null);
      })
      .catch(() => setEngines([]));
  }, []);

  const viewedPageEntry = pages?.find((p) => p.page === viewedPage) ?? null;

  return (
    <>
      <div className="header">
        <div className="wordmark">
          <div className="mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 20 L9 8 L13 15 L16 6 L20 20 Z" />
            </svg>
          </div>
          <h1>Document Extractor</h1>
        </div>
        <Stepper activeIndex={2} />
      </div>

      <div className="stage">
        <section className="card">
          <div className="res-inner">
            {error && <p style={{ color: "var(--hazard-rust)" }}>{error}</p>}

            {!error && !result && <p style={{ color: "var(--graphite)" }}>Loading result…</p>}

            {result && (
              <>
                <div className="res-top">
                  <div>
                    <h2>{resultTitle(result.document_type)}</h2>
                    <span className="sub">{id}</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 11 }}>
                    <span className="case-tag">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                      {caseTagLabel(result.document_type)}
                    </span>
                    <button type="button" className="back-btn" onClick={() => router.push("/")}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                        <path d="M19 12H5M12 19l-7-7 7-7" />
                      </svg>
                      Start over
                    </button>
                  </div>
                </div>
                <p className="route-line">
                  {result.pages_processed} pages processed
                  {pages && (
                    <>
                      {" "}
                      · {pages.filter((p) => p.type === "digital").length} digital ·{" "}
                      {pages.filter((p) => p.type === "scanned").length} scanned
                    </>
                  )}
                  {result.metadata.vendor && <> · {result.metadata.vendor}</>}
                  {result.metadata.invoiceNumber && <> · #{result.metadata.invoiceNumber}</>}
                </p>

                {pages && pages.length > 1 && (
                  <PageStrip
                    documentId={id}
                    pages={pages}
                    viewedPage={viewedPage}
                    onSelect={setViewedPage}
                    tables={result.tables ?? []}
                  />
                )}

                <FinalStageRow progress={progress} />
                {result.prescan && result.prescan.length > 0 && <QualityPanel prescan={result.prescan} />}

                <div className="di-main-split">
                  {pages && viewedPageEntry && (
                    <PageHighlightViewer
                      documentId={id}
                      pages={pages}
                      highlight={highlight}
                      viewedPage={viewedPage}
                      onPageChange={setViewedPage}
                    />
                  )}

                  <div className="tabs-panel">
                    <div className="tabs-head">
                      <button
                        type="button"
                        className={`tab-btn${activeTab === "ocr" ? " active" : ""}`}
                        onClick={() => setActiveTab("ocr")}
                      >
                        OCR text
                      </button>
                      <button
                        type="button"
                        className={`tab-btn${activeTab === "structured" ? " active" : ""}`}
                        onClick={() => setActiveTab("structured")}
                      >
                        Structured
                      </button>
                      <button
                        type="button"
                        className={`tab-btn${activeTab === "decision" ? " active" : ""}`}
                        onClick={() => setActiveTab("decision")}
                      >
                        Decision
                      </button>
                      <button
                        type="button"
                        className={`tab-btn${activeTab === "compare" ? " active" : ""}`}
                        onClick={() => setActiveTab("compare")}
                      >
                        Compare
                      </button>
                      <button
                        type="button"
                        className={`tab-btn${activeTab === "allresults" ? " active" : ""}`}
                        onClick={() => setActiveTab("allresults")}
                      >
                        All results
                      </button>
                      <div className="tab-spacer" />
                      {activeTab === "ocr" && viewedPageEntry?.type === "scanned" && engines.length > 0 && (
                        <div className="engine-select">
                          {engines.map((engine) => (
                            <button
                              key={engine.id}
                              type="button"
                              className={`engine-pill${ocrEngineId === engine.id ? " active" : ""}`}
                              onClick={() => setOcrEngineId(engine.id)}
                              disabled={!engine.available}
                              title={engine.available ? undefined : `${engine.name} is not currently available`}
                            >
                              {engine.name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    {(() => {
                      // Real continuation data (python/continuation.py) —
                      // only shows when the currently viewed page is
                      // actually part of a multi-page table.
                      const continuedTable = (result.tables ?? []).find(
                        (t) => t.pages.length > 1 && t.pages.includes(viewedPage),
                      );
                      if (!continuedTable) return null;
                      const isFirstPage = continuedTable.pages[0] === viewedPage;
                      const otherPage = isFirstPage
                        ? continuedTable.pages[continuedTable.pages.length - 1]
                        : continuedTable.pages[0];
                      return (
                        <div className="cont-banner">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <path d="M9 17H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v3M13 21l6-6M13 21h5v-5" />
                          </svg>
                          This table {isFirstPage ? "continues on" : "continues from"}{" "}
                          <a onClick={() => setViewedPage(otherPage)}>Page {otherPage}</a> — treated as one logical
                          table in All results.
                        </div>
                      );
                    })()}

                    <div className="tab-content">
                      {activeTab === "ocr" &&
                        (viewedPageEntry ? (
                          <OcrTextTab documentId={id} page={viewedPageEntry} engineId={ocrEngineId} engines={engines} />
                        ) : (
                          <div className="empty-tab">No page selected</div>
                        ))}

                      {activeTab === "structured" && (
                        <>
                          <StructuredFieldList result={result} />
                          <BOQTable result={result} onHover={setHighlight} />
                        </>
                      )}

                      {activeTab === "decision" && <DecisionTab result={result} />}

                      {activeTab === "compare" && pages && (
                        <CompareView
                          documentId={id}
                          pages={pages.map((p): PageRoute => ({ page: p.page, type: p.type }))}
                        />
                      )}

                      {activeTab === "allresults" && <AllResultsTab result={result} />}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
