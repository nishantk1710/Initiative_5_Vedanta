"use client";

import type { ExtractedValue, LineItem, ProcessResult } from "@/lib/types";
import type { Highlight } from "@/components/PageHighlightViewer";

export const ALL_FIELD_KEYS = ["itemCode", "description", "quantity", "unit", "rate", "amount", "taxRate", "taxAmount"] as const;
export type FieldKey = (typeof ALL_FIELD_KEYS)[number];

export const ENGINE_LABEL: Record<ExtractedValue["source"], string> = {
  pymupdf: "PyMuPDF",
  paddleocr: "PaddleOCR",
  tesseract: "Tesseract",
  llm: "AI-identified",
};

// Only the fields this row actually has — LineItem's optional columns
// (itemCode/unit/taxRate/taxAmount) may be entirely absent.
export function rowFieldKeys(row: LineItem): FieldKey[] {
  return ALL_FIELD_KEYS.filter((k) => row[k] !== undefined);
}

// Union bbox across every field this row actually has real bbox provenance
// for — mirrors pipeline.py's _row_display_regions, computed client-side so
// hovering a row can highlight its true source region on the page image.
function rowHighlight(row: LineItem): Highlight | null {
  const fields = rowFieldKeys(row)
    .map((k) => row[k])
    .filter((f): f is ExtractedValue<number | string> => !!f && f.bbox.some((v) => v !== 0));
  if (fields.length === 0) return null;
  return {
    page: fields[0].page,
    bbox: [
      Math.min(...fields.map((f) => f.bbox[0])),
      Math.min(...fields.map((f) => f.bbox[1])),
      Math.max(...fields.map((f) => f.bbox[2])),
      Math.max(...fields.map((f) => f.bbox[3])),
    ],
  };
}

// A field with no value was never extracted at all (build_line_items found
// nothing for that column in this row) — it's a "not applicable" placeholder,
// not a low-confidence read, and must never drag the row's displayed
// confidence toward 0%. Only fields that actually have a value contribute.
export function rowConfidence(row: LineItem): number {
  const scored = rowFieldKeys(row)
    .map((k) => row[k]!)
    .filter((f) => String(f.value).trim() !== "");
  if (scored.length === 0) return 0;
  return Math.min(...scored.map((f) => f.confidence));
}

// Which columns to show at all — a document with no invoice-only fields
// never gets an itemCode column, one with no `unit` on any row never gets
// a Unit column, etc. Order: itemCode, description, quantity, unit, rate,
// amount (tax fields feed validation but aren't given dedicated columns).
export function presentColumns(rows: LineItem[]): FieldKey[] {
  const columns: FieldKey[] = [];
  if (rows.some((r) => r.itemCode)) columns.push("itemCode");
  columns.push("description", "quantity");
  if (rows.some((r) => r.unit)) columns.push("unit");
  columns.push("rate", "amount");
  return columns;
}

export const COLUMN_LABEL: Record<FieldKey, string> = {
  itemCode: "Code",
  description: "Description",
  quantity: "Qty",
  unit: "Unit",
  rate: "Rate",
  amount: "Amount",
  taxRate: "Tax %",
  taxAmount: "Tax",
};

export const NUMERIC_COLUMNS: FieldKey[] = ["quantity", "rate", "amount", "taxRate", "taxAmount"];

export function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

// A table's display title reflects what it was actually tagged as — never
// hardcoded to "Invoice Items" for a table that might be a bank statement's
// transactions or an attendance sheet.
export function tableTitle(semanticRole: string): string {
  if (semanticRole === "unknown") return "Detected Table";
  return titleCase(semanticRole);
}

export default function BOQTable({
  result,
  onHover,
}: {
  result: ProcessResult;
  onHover?: (highlight: Highlight | null) => void;
}) {
  const { summary, lineItems, tables, fields } = result;
  const shownRows = lineItems.slice(0, 20);
  const moreCount = lineItems.length - shownRows.length;
  const columns = presentColumns(lineItems);
  const hasLineItems = lineItems.length > 0;
  const genericFieldEntries = Object.entries(fields ?? {});

  if (!hasLineItems && ((tables && tables.length > 0) || genericFieldEntries.length > 0)) {
    return (
      <>
        {genericFieldEntries.length > 0 && (
          <div className="generic-fields">
            <h3>Detected Fields</h3>
            <dl>
              {genericFieldEntries.map(([key, field]) => (
                <div key={key} className="field-row">
                  <dt>{titleCase(key)}</dt>
                  <dd>{field.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
        {(tables ?? []).map((table) => (
          <div key={table.table_id} className="generic-table">
            <h3>
              {tableTitle(table.semantic_role)}
              {table.semantic_role !== "unknown" && (
                <span className="sub"> · {Math.round(table.semantic_confidence * 100)}% confidence</span>
              )}
            </h3>
            {/* Real continuation pages from python/continuation.py's
                geometry-based linking — never an assumption about which
                pages might be related. */}
            {table.pages && table.pages.length > 1 && (
              <p className="continuation-note">
                This table spans pages {table.pages.join(", ")} — rows from all of them are merged here.
              </p>
            )}
            <table className="boq">
              <thead>
                <tr>
                  {table.headers.map((h, i) => (
                    <th key={i}>{h || `Column ${i + 1}`}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, i) => (
                  <tr
                    key={i}
                    onMouseEnter={() => onHover?.({ page: table.page, bbox: table.bbox })}
                    onMouseLeave={() => onHover?.(null)}
                  >
                    {row.map((cell, j) => (
                      <td key={j}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </>
    );
  }

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
          </tr>
        </thead>
        <tbody>
          {shownRows.map((row, i) => {
            const conf = rowConfidence(row);
            const confClass = conf >= 0.85 ? "ok" : "warn";
            const engine = row.description.source;
            const needsReview = row.status !== "valid";
            const highlight = rowHighlight(row);
            return (
              <tr
                key={i}
                className={needsReview ? `status-${row.status}` : undefined}
                onMouseEnter={() => highlight && onHover?.(highlight)}
                onMouseLeave={() => onHover?.(null)}
              >
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
              </tr>
            );
          })}
        </tbody>
      </table>
      {moreCount > 0 && <p className="more-rows">+ {moreCount} more rows</p>}
    </>
  );
}
