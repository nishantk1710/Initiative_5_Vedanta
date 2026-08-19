"use client";

import type { BoqField, BoqRow, ProcessResult } from "@/lib/types";

const FIELD_ORDER: Array<keyof Pick<BoqRow, "description" | "quantity" | "unit" | "rate" | "amount">> = [
  "description",
  "quantity",
  "unit",
  "rate",
  "amount",
];

const ENGINE_LABEL: Record<BoqField["source"], string> = {
  pymupdf: "PyMuPDF",
  paddleocr: "PaddleOCR",
  tesseract: "Tesseract",
};

function rowConfidence(row: BoqRow): number {
  return Math.min(...FIELD_ORDER.map((f) => row[f].confidence));
}

function firstNonValidField(row: BoqRow): (typeof FIELD_ORDER)[number] {
  return FIELD_ORDER.find((f) => row[f].status && row[f].status !== "valid") ?? "description";
}

export default function BOQTable({
  result,
  onViewSource,
}: {
  result: ProcessResult;
  onViewSource: (row: BoqRow, field: (typeof FIELD_ORDER)[number]) => void;
}) {
  const { summary, boq } = result;
  const shownRows = boq.slice(0, 20);
  const moreCount = boq.length - shownRows.length;

  return (
    <>
      <div className="stat-row">
        <div className="stat total">
          <div className="top-row">
            <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
              <rect x="4" y="4" width="16" height="16" rx="2" />
              <path d="M4 10h16M10 4v16" />
            </svg>
          </div>
          <span className="num">{summary.total_rows}</span>
          <span className="lbl">BOQ rows</span>
        </div>
        <div className="stat valid">
          <div className="top-row">
            <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </div>
          <span className="num">{summary.valid_rows}</span>
          <span className="lbl">Valid</span>
        </div>
        <div className="stat review">
          <div className="top-row">
            <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
              <path d="M12 9v4M12 17h.01M10.3 3.9L2.6 18a1 1 0 0 0 .9 1.5h17a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.7 0Z" />
            </svg>
          </div>
          <span className="num">{summary.review_rows}</span>
          <span className="lbl">Need review</span>
        </div>
        <div className="stat llm">
          <div className="top-row">
            <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
              <path d="M12 3v3M12 18v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M3 12h3M18 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </div>
          <span className="num">{summary.llm_normalized_fields}</span>
          <span className="lbl">LLM-normalized</span>
        </div>
      </div>

      <table className="boq">
        <thead>
          <tr>
            <th>Description</th>
            <th className="num">Qty</th>
            <th>Unit</th>
            <th className="num">Rate</th>
            <th className="num">Amount</th>
            <th className="num">Confidence</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {shownRows.map((row, i) => {
            const conf = rowConfidence(row);
            const confClass = conf >= 0.85 ? "ok" : "warn";
            const engine = row.description.source;
            const needsReview = row.status !== "valid";
            return (
              <tr key={i} className={needsReview ? `status-${row.status}` : undefined}>
                <td>
                  <span className="desc-name">{row.description.value || "—"}</span>
                  <span className={`engine-tag ${engine}`}>
                    <span className="dot" />
                    {ENGINE_LABEL[engine]}
                  </span>
                </td>
                <td className="num">{row.quantity.value}</td>
                <td>{row.unit.value}</td>
                <td className="num">{row.rate.value}</td>
                <td className="num">{row.amount.value}</td>
                <td className="conf-cell">
                  <span className={`conf-pill ${confClass}`}>
                    <span className="cdot" />
                    {Math.round(conf * 100)}%
                  </span>
                </td>
                <td className="action-cell">
                  {needsReview ? (
                    <button
                      type="button"
                      className="view-src"
                      onClick={() => onViewSource(row, firstNonValidField(row))}
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                      View source
                    </button>
                  ) : (
                    <span className="ok-mark">✓</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {moreCount > 0 && <p className="more-rows">+ {moreCount} more rows</p>}
    </>
  );
}
