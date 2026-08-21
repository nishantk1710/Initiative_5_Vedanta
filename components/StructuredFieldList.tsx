"use client";

import type { DocumentMetadata, ProcessResult } from "@/lib/types";

type DotColor = "green" | "amber" | "gray";

function confidenceDot(confidence: number | null): DotColor {
  if (confidence === null) return "gray";
  if (confidence >= 0.85) return "green";
  if (confidence > 0) return "amber";
  return "gray";
}

function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

interface FieldRow {
  key: string;
  label: string;
  value: string;
  // null = genuinely not tracked for this field (e.g. metadata_extractor.py's
  // regex fields carry no confidence score at all) — rendered as "n/a", never
  // as a fabricated percentage.
  confidence: number | null;
}

// metadata_extractor.py's dedicated invoice fields are plain strings with no
// per-field confidence in the data model — showing a fabricated number for
// them would violate the same "never invent a confidence" rule applied to
// PaddleOCR-VL elsewhere. They're listed with an honest "n/a" instead.
const METADATA_FIELD_LABELS: Record<keyof Omit<DocumentMetadata, "documentType" | "totals">, string> = {
  vendor: "Vendor",
  invoiceNumber: "Invoice Number",
  date: "Date",
  buyer: "Buyer",
};

function buildFieldRows(result: ProcessResult): FieldRow[] {
  const rows: FieldRow[] = [];
  const { metadata, fields } = result;

  for (const key of Object.keys(METADATA_FIELD_LABELS) as Array<keyof typeof METADATA_FIELD_LABELS>) {
    const value = metadata[key];
    if (value === undefined || value === "") continue;
    rows.push({ key, label: METADATA_FIELD_LABELS[key], value: String(value), confidence: null });
  }

  if (metadata.totals) {
    for (const [totalKey, totalValue] of Object.entries(metadata.totals)) {
      if (totalValue === undefined) continue;
      rows.push({
        key: `totals.${totalKey}`,
        label: titleCase(totalKey),
        value: String(totalValue),
        confidence: null,
      });
    }
  }

  for (const [key, field] of Object.entries(fields ?? {})) {
    rows.push({ key, label: titleCase(key), value: field.value, confidence: field.confidence });
  }

  return rows;
}

function extractionPathBadge(result: ProcessResult): string {
  const path = result.extraction_path === "llm_text_fallback" ? "LLM text fallback" : "Geometry table detection";
  const typeLabel = titleCase(String(result.document_type));
  const confidencePct =
    result.document_type_confidence !== undefined ? ` · ${Math.round(result.document_type_confidence * 100)}%` : "";
  return `${typeLabel}${confidencePct} · ${path}`;
}

export default function StructuredFieldList({ result }: { result: ProcessResult }) {
  const rows = buildFieldRows(result);
  if (rows.length === 0) return null;

  return (
    <div className="structured-fields">
      <div className="extraction-path-badge">{extractionPathBadge(result)}</div>
      <table className="field-list-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
            <th className="num">Confidence</th>
            <th aria-hidden />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const dot = confidenceDot(row.confidence);
            return (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{row.value}</td>
                <td className="num">{row.confidence !== null ? `${Math.round(row.confidence * 100)}%` : "n/a"}</td>
                <td>
                  <span className={`confidence-dot dot-${dot}`} title={row.confidence === null ? "not tracked" : dot} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
