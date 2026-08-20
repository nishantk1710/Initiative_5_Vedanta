"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Stepper from "@/components/Stepper";
import BOQTable from "@/components/BOQTable";
import SourceViewer from "@/components/SourceViewer";
import type { DocumentType, LineItem, PageRegionsEntry, ProcessResult } from "@/lib/types";

type FieldName = "itemCode" | "description" | "quantity" | "unit" | "rate" | "amount" | "taxRate" | "taxAmount";

const CASE_TAG_LABEL: Record<DocumentType, string> = {
  invoice: "Invoice",
  boq: "Mining SOW",
  unknown: "Unrecognized document",
};

const RESULT_TITLE: Record<DocumentType, string> = {
  invoice: "Invoice Result",
  boq: "Mining SOW Result",
  unknown: "Document Result",
};

export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [result, setResult] = useState<ProcessResult | null>(null);
  const [pages, setPages] = useState<PageRegionsEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ row: LineItem; field: FieldName } | null>(null);

  useEffect(() => {
    Promise.all([
      fetch(`/api/result/${id}`).then((r) => {
        if (!r.ok) throw new Error(`No result found for ${id}`);
        return r.json() as Promise<ProcessResult>;
      }),
      fetch(`/api/result/${id}/pages`).then((r) => (r.ok ? (r.json() as Promise<PageRegionsEntry[]>) : [])),
    ])
      .then(([resultData, pagesData]) => {
        setResult(resultData);
        setPages(pagesData);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load result"));
  }, [id]);

  const pageDims = new Map((pages ?? []).map((p) => [p.page, { width: p.width, height: p.height }]));

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
                    <h2>{RESULT_TITLE[result.document_type]}</h2>
                    <span className="sub">{id}</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 11 }}>
                    <span className="case-tag">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                      {CASE_TAG_LABEL[result.document_type]}
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

                <BOQTable
                  result={result}
                  onViewSource={(row, field) => setModal({ row, field })}
                />
              </>
            )}
          </div>
        </section>
      </div>

      {modal &&
        (() => {
          const field = modal.row[modal.field];
          if (!field) return null;
          const dims = pageDims.get(field.page);
          if (!dims) return null;
          return (
            <SourceViewer
              documentId={id}
              row={modal.row}
              fieldName={modal.field}
              pageWidth={dims.width}
              pageHeight={dims.height}
              onClose={() => setModal(null)}
            />
          );
        })()}
    </>
  );
}
