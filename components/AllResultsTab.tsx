"use client";

import { Fragment } from "react";
import type { LineItem, ProcessResult } from "@/lib/types";
import {
  COLUMN_LABEL,
  ENGINE_LABEL,
  NUMERIC_COLUMNS,
  presentColumns,
  rowConfidence,
  tableTitle,
} from "@/components/BOQTable";

// Groups rows by their real page number into contiguous runs — this is
// NOT continuation detection (line_items.py doesn't merge rows across
// pages the way continuation.py does for generic tables); it's just a
// display grouping so "page 3's rows" and "page 4's rows" don't blur
// together, using each row's own real page field.
function groupLineItemsByPage(rows: LineItem[]): { page: number; rows: LineItem[] }[] {
  const byPage = new Map<number, LineItem[]>();
  for (const row of rows) {
    const page = row.description.page;
    if (!byPage.has(page)) byPage.set(page, []);
    byPage.get(page)!.push(row);
  }
  return Array.from(byPage.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([page, rows]) => ({ page, rows }));
}

export default function AllResultsTab({ result }: { result: ProcessResult }) {
  const { lineItems, tables, summary, pages_processed } = result;
  const lineItemGroups = groupLineItemsByPage(lineItems);
  const columns = presentColumns(lineItems);
  const genericTables = tables ?? [];

  const nothingToShow = lineItemGroups.length === 0 && genericTables.length === 0;

  return (
    <>
      <div className="results-summary">
        <div className="rstat">
          <div className="num">{pages_processed}</div>
          <div className="lbl">Pages processed</div>
        </div>
        <div className="rstat">
          <div className="num">{summary.total_rows}</div>
          <div className="lbl">Line items</div>
        </div>
        <div className="rstat">
          <div className="num">{summary.review_rows + summary.incomplete_rows}</div>
          <div className="lbl">Need review</div>
        </div>
        {genericTables.length > 0 && (
          <div className="rstat">
            <div className="num">{genericTables.length}</div>
            <div className="lbl">Other tables</div>
          </div>
        )}
      </div>

      {nothingToShow && <div className="empty-tab">No line items or tables were found in this document.</div>}

      {lineItemGroups.length > 0 && (
        <table className="results-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col} className={NUMERIC_COLUMNS.includes(col) ? "r" : undefined}>
                  {COLUMN_LABEL[col]}
                </th>
              ))}
              <th>Engine</th>
              <th className="r">Conf</th>
            </tr>
          </thead>
          <tbody>
            {lineItemGroups.map((group) => (
              <Fragment key={`g-${group.page}`}>
                <tr className="group-row">
                  <td colSpan={columns.length + 2}>Line items · Page {group.page}</td>
                </tr>
                {group.rows.map((row, i) => {
                  const conf = rowConfidence(row);
                  return (
                    <tr key={`${group.page}-${i}`}>
                      {columns.map((col) => {
                        const field = row[col];
                        return (
                          <td key={col} className={NUMERIC_COLUMNS.includes(col) ? "r" : undefined}>
                            {field?.value ?? ""}
                          </td>
                        );
                      })}
                      <td>
                        <span className="engine-chip">{ENGINE_LABEL[row.description.source]}</span>
                      </td>
                      <td className="r">
                        <span className={`conf-chip ${conf >= 0.85 ? "ok" : "warn"}`}>{Math.round(conf * 100)}%</span>
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      {genericTables.map((table) => {
        const isContinued = table.pages.length > 1;
        const label = isContinued
          ? `${tableTitle(table.semantic_role)} · Pages ${table.pages.join("–")} (continued)`
          : `${tableTitle(table.semantic_role)} · Page ${table.pages[0] ?? table.page}`;
        return (
          <table className="results-table" key={table.table_id} style={{ marginTop: 14 }}>
            <thead>
              <tr className={`group-row${isContinued ? " continued" : ""}`}>
                <th colSpan={Math.max(table.headers.length, 1)}>{label}</th>
              </tr>
              <tr>
                {table.headers.map((h, i) => (
                  <th key={i}>{h || `Column ${i + 1}`}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}
    </>
  );
}
