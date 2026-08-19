import "server-only";
import type { PrepareResult, ProcessResult } from "./types";

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

export async function processDocument(
  documentId: string,
  filePath: string,
): Promise<ProcessResult> {
  return pythonFetch<ProcessResult>("/process", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, file_path: filePath }),
  });
}
