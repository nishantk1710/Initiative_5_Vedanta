"use client";

import type { ExtractedValue, LineItem, ProcessResult } from "@/lib/types";

const ALL_FIELD_KEYS = ["itemCode", "description", "quantity", "unit", "rate", "amount", "taxRate", "taxAmount"] as const;
type FieldKey = (typeof ALL_FIELD_KEYS)[number];

const ENGINE_LABEL: Record<ExtractedValue["source"], string> = {
  pymupdf: "PyMuPDF",
  paddleocr: "PaddleOCR",
  tesseract: "Tesseract",
};

// Only the fields this row actually has — LineItem's optional columns
// (itemCode/unit/taxRate/taxAmount) may be entirely absent.
function rowFieldKeys(row: LineItem): FieldKey[] {
  return ALL_FIELD_KEYS.filter((k) => row[k] !== undefined);
}

// A field with no value was never extracted at all (build_line_items found
// nothing for that column in this row) — it's a "not applicable" placeholder,
// not a low-confidence read, and must never drag the row's displayed
// confidence toward 0%. Only fields that actually have a value contribute.
function rowConfidence(row: LineItem): number {
  const scored = rowFieldKeys(row)
    .map((k) => row[k]!)
    .filter((f) => String(f.value).trim() !== "");
  if (scored.length === 0) return 0;
  return Math.min(...scored.map((f) => f.confidence));
}

function firstNonValidField(row: LineItem): FieldKey {
  const keys = rowFieldKeys(row);
  const withValue = keys.find(
    (k) => row[k]!.status && row[k]!.status !== "valid" && String(row[k]!.value).trim() !== "",
  );
  if (withValue) return withValue;
  return keys.find((k) => row[k]!.status && row[k]!.status !== "valid") ?? "description";
}

// Which columns to show at all — a document with no invoice-only fields
// never gets an itemCode column, one with no `unit` on any row never gets
// a Unit column, etc. Order: itemCode, description, quantity, unit, rate,
// amount (tax fields feed validation but aren't given dedicated columns).
function presentColumns(rows: LineItem[]): FieldKey[] {
  const columns: FieldKey[] = [];
  if (rows.some((r) => r.itemCode)) columns.push("itemCode");
  columns.push("description", "quantity");
  if (rows.some((r) => r.unit)) columns.push("unit");
  columns.push("rate", "amount");
  return columns;
}

const COLUMN_LABEL: Record<FieldKey, string> = {
  itemCode: "Code",
  description: "Description",
  quantity: "Qty",
  unit: "Unit",
  rate: "Rate",
  amount: "Amount",
  taxRate: "Tax %",
  taxAmount: "Tax",
};

const NUMERIC_COLUMNS: FieldKey[] = ["quantity", "rate", "amount", "taxRate", "taxAmount"];

export default function BOQTable({
  result,
  onViewSource,
}: {
  result: ProcessResult;
  onViewSource: (row: LineItem, field: FieldKey) => void;
}) {
  const { summary, lineItems } = result;
  const shownRows = lineItems.slice(0, 20);
  const moreCount = lineItems.length - shownRows.length;
  const columns = presentColumns(lineItems);

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
          <span className="lbl">Line items</span>
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
            {columns.map((col) => (
              <th key={col} className={NUMERIC_COLUMNS.includes(col) ? "num" : undefined}>
                {COLUMN_LABEL[col]}
              </th>
            ))}
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
                {columns.map((col) => {
                  const field = row[col];
                  if (col === "description") {
                    return (
                      <td key={col}>
                        <span className="desc-name">{field?.value ?? "—"}</span>
                        <span className={`engine-tag ${engine}`}>
                          <span className="dot" />
                          {ENGINE_LABEL[engine]}
                        </span>
                      </td>
                    );
                  }
                  return (
                    <td key={col} className={NUMERIC_COLUMNS.includes(col) ? "num" : undefined}>
                      {field?.value ?? ""}
                    </td>
                  );
                })}
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
