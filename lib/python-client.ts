import "server-only";
import type { CompareResult, EngineInfo, PrepareResult, ProcessingProgress } from "./types";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://localhost:8000";

async function pythonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PYTHON_API_URL}${path}`, init);
  if (!res.ok) {
    throw new Error(`Python API error ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export async function prepareDocument(
  documentId: string,
  filePath: string,
): Promise<PrepareResult> {
  return pythonFetch<PrepareResult>("/prepare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, file_path: filePath }),
  });
}

export interface StartProcessingResult {
  job_id: string;
  status: "queued";
  pages_total: number;
}

// Async job model: a 10+ page scanned document can genuinely take
// 10-15+ minutes, which would time out a synchronous HTTP call — this
// returns IMMEDIATELY with the job's real page count while the Python
// service runs the actual pipeline as a background task. Poll
// getProcessingProgress() for real per-page status; fetch the final
// ProcessResult from /api/result/{id} once status is "completed".
export async function startProcessing(
  documentId: string,
  filePath: string,
): Promise<StartProcessingResult> {
  return pythonFetch<StartProcessingResult>("/process", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, file_path: filePath }),
  });
}

// Real per-stage progress, written by python/progress.py DURING the
// in-flight /process call — returns null (not a thrown error) once the
// call has finished and results/<id>/progress.json's status has moved on,
// or before any progress has been recorded yet, since a 404 here just
// means "nothing to report right now," not a failure worth surfacing.
export async function getProcessingProgress(documentId: string): Promise<ProcessingProgress | null> {
  try {
    return await pythonFetch<ProcessingProgress>(`/status/${documentId}`);
  } catch {
    return null;
  }
}

// Runs the requested OCR engines against one already-rendered page and
// returns their raw output side by side — see python/engine_compare.py.
// Throws (rather than swallowing) on failure: unlike progress polling,
// a Compare request is always user-initiated, so a real error should
// surface to that click rather than disappear.
export async function compareEngines(
  documentId: string,
  pageNumber: number,
  engines?: string[],
): Promise<CompareResult> {
  const query = engines && engines.length > 0 ? `?engines=${engines.join(",")}` : "";
  return pythonFetch<CompareResult>(`/compare/${documentId}/${pageNumber}${query}`);
}

// The actual configured/available OCR engines — see engine_compare.py's
// ENGINE_METADATA. Never hardcode an engine's name/id/confidence-exposure
// in a frontend component; fetch this instead.
export async function listEngines(): Promise<EngineInfo[]> {
  const { engines } = await pythonFetch<{ engines: EngineInfo[] }>("/engines");
  return engines;
}
