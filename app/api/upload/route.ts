import { NextResponse } from "next/server";
import { randomUUID } from "crypto";
import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { z } from "zod";
import { detectFileExtension } from "@/lib/uploaded-file";

export const runtime = "nodejs";

const MAX_SIZE_BYTES = 25 * 1024 * 1024;

const metadataSchema = z
  .object({
    originalFilename: z.string().min(1).max(255).optional(),
  })
  .optional();

function sanitizeFilename(name: string): string {
  const base = path.basename(name).replace(/[^a-zA-Z0-9._-]/g, "_");
  return base.length > 0 ? base : "upload";
}

export async function POST(request: Request) {
  const formData = await request.formData();
  const file = formData.get("file");

  if (!(file instanceof File)) {
    return NextResponse.json({ error: "Missing 'file' field" }, { status: 400 });
  }

  const rawMetadata = formData.get("metadata");
  if (typeof rawMetadata === "string") {
    let parsedMetadata: unknown;
    try {
      parsedMetadata = JSON.parse(rawMetadata);
    } catch {
      return NextResponse.json({ error: "Invalid metadata JSON" }, { status: 400 });
    }
    const result = metadataSchema.safeParse(parsedMetadata);
    if (!result.success) {
      return NextResponse.json(
        { error: "Invalid metadata shape", details: result.error.flatten() },
        { status: 400 },
      );
    }
  }

  if (file.size === 0) {
    return NextResponse.json({ error: "Empty file" }, { status: 400 });
  }

  if (file.size > MAX_SIZE_BYTES) {
    return NextResponse.json(
      { error: `File exceeds ${MAX_SIZE_BYTES / (1024 * 1024)}MB limit` },
      { status: 400 },
    );
  }

  const buffer = Buffer.from(await file.arrayBuffer());

  const ext = detectFileExtension(buffer);
  if (!ext) {
    return NextResponse.json(
      { error: "Unsupported file type — only PDF, PNG, and JPEG are accepted (checked by content, not filename)" },
      { status: 400 },
    );
  }

  const sanitizedName = sanitizeFilename(file.name || `upload.${ext}`);
  const documentId = randomUUID().slice(0, 8);

  const uploadsDir = path.join(process.cwd(), "uploads");
  await mkdir(uploadsDir, { recursive: true });
  const destPath = path.join(uploadsDir, `${documentId}.${ext}`);
  await writeFile(destPath, buffer);

  return NextResponse.json({
    documentId,
    filename: sanitizedName,
    status: "uploaded",
  });
}
