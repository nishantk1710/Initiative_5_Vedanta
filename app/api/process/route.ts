import { NextResponse } from "next/server";
import path from "path";
import { z } from "zod";
import { processDocument } from "@/lib/python-client";
import { resolveUploadedFilePath } from "@/lib/uploaded-file";

export const runtime = "nodejs";

const requestSchema = z.object({
  documentId: z.string().min(1),
});

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const result = requestSchema.safeParse(body);
  if (!result.success) {
    return NextResponse.json(
      { error: "Invalid request shape", details: result.error.flatten() },
      { status: 400 },
    );
  }

  const { documentId } = result.data;
  const safeId = path.basename(documentId);
  const uploadsDir = path.join(process.cwd(), "uploads");
  const filePath = await resolveUploadedFilePath(uploadsDir, safeId);
  if (!filePath) {
    return NextResponse.json({ error: `No uploaded file found for document ${safeId}` }, { status: 404 });
  }

  try {
    const routeResult = await processDocument(safeId, filePath);
    return NextResponse.json(routeResult);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Processing failed" },
      { status: 502 },
    );
  }
}
