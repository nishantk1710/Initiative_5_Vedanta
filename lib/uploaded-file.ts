import "server-only";
import { readdir } from "fs/promises";
import path from "path";

// Server-side only: real file-type detection by magic bytes, never trusted
// from the client's declared MIME type or filename extension.
const SIGNATURES: Array<{ ext: string; bytes: number[] }> = [
  { ext: "pdf", bytes: [0x25, 0x50, 0x44, 0x46, 0x2d] }, // %PDF-
  { ext: "png", bytes: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] },
  { ext: "jpg", bytes: [0xff, 0xd8, 0xff] },
];

export function detectFileExtension(buffer: Buffer): string | null {
  for (const sig of SIGNATURES) {
    if (buffer.length >= sig.bytes.length && sig.bytes.every((b, i) => buffer[i] === b)) {
      return sig.ext;
    }
  }
  return null;
}

const ALLOWED_EXTENSIONS = SIGNATURES.map((s) => s.ext);

// Uploads are saved as <documentId>.<real-extension>, so callers that only
// have the documentId (e.g. /api/process, /api/prepare) need to look up
// which extension it actually landed under.
export async function resolveUploadedFilePath(uploadsDir: string, documentId: string): Promise<string | null> {
  const entries = await readdir(uploadsDir).catch(() => [] as string[]);
  for (const ext of ALLOWED_EXTENSIONS) {
    const candidate = `${documentId}.${ext}`;
    if (entries.includes(candidate)) {
      return path.join(uploadsDir, candidate);
    }
  }
  return null;
}
