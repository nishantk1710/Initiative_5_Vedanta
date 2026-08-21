export type PageType = "digital" | "scanned";

export type FieldStatus = "valid" | "review" | "ambiguous" | "incomplete";

// "llm" marks a value whose structure was inferred from text by the model
// (llm_line_items.py fallback) rather than read directly by an OCR/text
// engine — kept distinct so provenance stays honest in the UI.
export type ExtractionSource = "pymupdf" | "paddleocr" | "tesseract" | "llm";

export interface ExtractedValue<T = string> {
  value: T;
  source: ExtractionSource;
  confidence: number;
  page: number;
  bbox: [number, number, number, number];
  status?: FieldStatus;
  rules_triggered?: string[];
}

// Generalized from BOQ-only rows to invoices/receipts too. Optional fields
// are omitted entirely (not present as a key) when not applicable to the
// document — an invoice row has no `unit`, a BOQ row has no `itemCode`.
// Numeric fields are typed ExtractedValue<number>, but a value that failed
// to parse (e.g. OCR misread "12S0") is left as the raw string so
// numeric_parse_failure can still surface it — treat `value` defensively.
export interface LineItem {
  itemCode?: ExtractedValue<string>; // HSN/SKU code — invoices only
  description: ExtractedValue<string>;
  quantity: ExtractedValue<number | string>;
  unit?: ExtractedValue<string>; // m3/hr — mostly BOQ, often absent on invoices
  rate: ExtractedValue<number | string>;
  amount: ExtractedValue<number | string>;
  taxRate?: ExtractedValue<number | string>; // invoices only
  taxAmount?: ExtractedValue<number | string>; // invoices only
  status: FieldStatus;
  rules_triggered?: string[];
}

// Open vocabulary: classifier.py can report any type it has a signal set
// for (see python/classifier.py's SIGNAL_SETS), plus "unknown" when no type
// is confidently matched. The named literals are commonly-seen values for
// editor autocomplete/discoverability — they are hints, not an exhaustive
// list, so a value outside this set (a new signal set added server-side)
// must still be handled gracefully rather than rejected.
export type DocumentType =
  | "boq"
  | "invoice"
  | "bank_statement"
  | "resume"
  | "contract"
  | "purchase_order"
  | "receipt"
  | "unknown"
  | (string & {});

export interface DocumentTypeCandidate {
  value: DocumentType;
  confidence: number;
}

// A physically-reconstructed table whose header didn't match a known
// BOQ/invoice column set — see python/generic_tables.py +
// python/table_semantics.py. semantic_role is "unknown" when no role was
// confidently identified; the table's raw shape is still reported either
// way rather than being discarded.
export interface GenericTable {
  table_id: string;
  page: number;
  // Every page this table's rows actually came from, from real bbox/column
  // continuation detection (python/continuation.py) — [page] for a
  // standalone table, [p1, p2, ...] when a table split across a page break
  // was linked into one logical table. Never assume length 1.
  pages: number[];
  bbox: [number, number, number, number];
  headers: string[];
  rows: string[][];
  row_count: number;
  semantic_role: string;
  semantic_confidence: number;
  column_bounds?: [number, number][];
}

// A "Label: value" field discovered outside any known invoice pattern —
// see python/generic_fields.py. Keyed dynamically; a field that wasn't
// found in the document simply isn't a key here (never null-padded).
export interface GenericField {
  value: string;
  confidence: number;
  source: "regex";
}

// Pre-scan quality-gate result for one page — see python/prescan.py.
// Thresholds are heuristic/uncalibrated; "fail" is a warning to the user,
// never a reason the page wasn't processed.
// Mirrors python/engine_compare.py's output. An engine that isn't
// installed/available reports `available: false` with a `reason` and no
// other fields — never a fabricated result.
export type EngineCompareEntry =
  | { engine: string; available: false; reason: string }
  | {
      engine: string;
      available: true;
      latency_ms: number;
      value_count: number;
      text: string;
      confidence_available: boolean;
      average_confidence: number | null;
      values: Array<Record<string, unknown>>;
    };

export interface CompareResult {
  page: number;
  results: EngineCompareEntry[];
}

export interface PrescanResult {
  page: number;
  dpi: number;
  sharpness: number;
  contrast: number;
  brightness: number;
  status: "pass" | "warn" | "fail";
  reasons: string[];
}

// Extracted separately from line items via lightweight pattern matching
// against header/receiver/footer text — never from table content.
export interface DocumentMetadata {
  documentType: DocumentType;
  vendor?: string;
  invoiceNumber?: string;
  date?: string;
  buyer?: string;
  totals?: { subtotal?: number; tax?: number; grandTotal?: number };
}

export interface ProcessResult {
  document_id: string;
  document_type: DocumentType;
  // Additive: confidence + alternate candidates for document_type, from
  // python/classifier.py's open-vocabulary classification. Optional so a
  // ProcessResult from before this field existed still type-checks.
  document_type_confidence?: number;
  document_type_candidates?: DocumentTypeCandidate[];
  pages_processed: number;
  status: string;
  metadata: DocumentMetadata;
  // "table_regions" = primary path (PP-StructureV3 detected a real table).
  // "llm_text_fallback" = no table region was detected, so the page's text
  // was handed to the LLM to identify line items instead.
  extraction_path?: "table_regions" | "llm_text_fallback";
  summary: {
    total_rows: number;
    valid_rows: number;
    review_rows: number;
    incomplete_rows: number;
    llm_normalized_fields: number;
  };
  lineItems: LineItem[];
  // Tables reconstructed outside the BOQ/invoice line-item path (e.g. a
  // bank statement's transaction table) — absent or empty when there are
  // none, never padded with placeholder entries.
  tables?: GenericTable[];
  // Generic "Label: value" fields found outside any known invoice pattern —
  // see DocumentMetadata for the dedicated invoice fields.
  fields?: Record<string, GenericField>;
  // One entry per page — see python/prescan.py. Absent on a ProcessResult
  // from before this field existed.
  prescan?: PrescanResult[];
}

export type SelectedSource =
  | { type: "sample"; file: string }
  | { type: "upload"; file: File };

export interface UploadResponse {
  documentId: string;
  filename: string;
  status: "uploaded";
}

// Precomputed (real router output) at dev-time for the 3 bundled samples —
// see lib/sample-metadata.json, generated by running inspect_document()
// directly against public/samples/*.pdf.
export interface SampleMetadata {
  pages: PageRoute[];
  digitalCount: number;
  scannedCount: number;
  thumbnail: string;
}

export interface PageRoute {
  page: number;
  type: PageType;
}

export interface PrepareResult {
  document_id: string;
  pages: PageRoute[];
}

// Mirrors python/progress.py's ProgressTracker output — the real, live
// per-stage state of an in-flight /process call, read from
// results/<id>/progress.json rather than approximated client-side.
export type PipelineStage =
  | "loading"
  | "routing"
  | "rendering"
  | "prescan"
  | "layout_detection"
  | "ocr"
  | "handwriting_ocr"
  | "document_understanding"
  | "schema_discovery"
  | "semantic_extraction"
  | "validation"
  | "finalization";

// The 4 named groups python/progress.py actually reports per page — a
// page's real state, never simulated ("running" only appears here once
// that page's work genuinely started).
export type StageGroupName = "prescan" | "ocr" | "structure" | "decide";
export type StageGroupState = "pending" | "running" | "done";

export interface PageProgress {
  page: number;
  status: "queued" | "active" | "done";
  kind: PageType;
  stages: Record<StageGroupName, StageGroupState>;
}

export interface ProcessingProgress {
  job_id?: string;
  status: "queued" | "processing" | "completed" | "error";
  current_stage: PipelineStage | null;
  completed_stages: PipelineStage[];
  // Real measured wall-clock time per completed stage (python/progress.py),
  // keyed by stage name. A stage that never ran for this document is simply
  // absent — never a fabricated 0.
  stage_durations_ms: Partial<Record<PipelineStage, number>>;
  // Real per-page state — length always equals pages_total, driven
  // entirely by python/progress.py's ProgressTracker, never assumed or
  // hardcoded client-side. See PageProgress.
  pages_total: number;
  pages: PageProgress[];
  live_page: number | null;
  error?: string;
}

// GET /engines — the actual configured/available OCR engines, so the
// frontend never hardcodes an engine's display name or whether it exposes
// per-value confidence (see python/engine_compare.py's ENGINE_METADATA).
export interface EngineInfo {
  id: string;
  name: string;
  exposes_confidence: boolean;
  available: boolean;
}

// One entry per page in results/<id>/regions.json. `regions` shape differs
// by branch: digital pages hold ExtractedValue-shaped PyMuPDF text blocks,
// scanned pages hold PP-StructureV3 layout regions ({type, bbox, category}).
export interface PageRegionsEntry {
  page: number;
  type: PageType;
  width: number;
  height: number;
  regions: Array<Record<string, unknown>>;
}
