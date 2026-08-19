import { NextResponse } from "next/server";
import path from "path";
import { z } from "zod";
import { processDocument } from "@/lib/python-client";

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
  const filePath = path.join(process.cwd(), "uploads", `${safeId}.pdf`);

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
