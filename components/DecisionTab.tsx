"use client";

import type { LineItem, ProcessResult } from "@/lib/types";

// Human-readable text for the rule codes rules.py actually emits (see
// python/rules.py / python/correction.py) — a lookup, not a re-derivation;
// falls back to the raw code for anything not yet mapped so nothing is
// ever silently dropped.
const RULE_TEXT: Record<string, string> = {
  arithmetic_mismatch: "quantity × rate did not match the printed amount within tolerance",
  confidence_below_review_threshold: "OCR confidence too low to trust without review",
  confidence_below_accept_threshold: "OCR confidence below the auto-accept threshold",
  numeric_parse_failure: "value could not be parsed as a number",
  required_field_missing: "a required field was not extracted",
  llm_extracted_structure: "row structure was inferred by the LLM fallback, not read by geometry",
  llm_corrected: "a correlated field was corrected by the safe-correction protocol",
  table_header_not_identified: "table header could not be confidently mapped to known columns",
};

function ruleText(rule: string): string {
  const [, code] = rule.includes(":") ? rule.split(":", 2) : [null, rule];
  return RULE_TEXT[code] ?? code;
}

function rowLabel(row: LineItem): string {
  return String(row.description?.value ?? "line item");
}

export default function DecisionTab({ result }: { result: ProcessResult }) {
  const { lineItems, summary } = result;
  const flagged = lineItems.filter((row) => row.status !== "valid");
  const validCount = summary.valid_rows;

  return (
    <>
      <div className="badge-row">
        <span className="badge pct">{summary.valid_rows} valid</span>
        <span className="badge warn">{summary.review_rows} review</span>
        <span className="badge">{summary.incomplete_rows} incomplete</span>
        {summary.llm_normalized_fields > 0 && (
          <span className="badge">{summary.llm_normalized_fields} LLM-corrected field(s)</span>
        )}
      </div>

      {validCount > 0 && (
        <div className="decision-card">
          <div className="top">
            <span className="field">{validCount} line item(s) passed validation</span>
            <span className="status valid">valid</span>
          </div>
          <div className="reason">Arithmetic, confidence, and required-field checks all passed.</div>
        </div>
      )}

      {flagged.map((row, i) => (
        <div className="decision-card" key={i}>
          <div className="top">
            <span className="field">{rowLabel(row)}</span>
            <span className={`status ${row.status === "incomplete" ? "review" : row.status}`}>{row.status}</span>
          </div>
          <div className="reason">
            {(row.rules_triggered ?? []).length > 0
              ? row.rules_triggered!.map(ruleText).join("; ")
              : "flagged for review"}
          </div>
        </div>
      ))}

      {lineItems.length === 0 && <div className="empty-tab">No line items to validate on this document.</div>}
    </>
  );
}
