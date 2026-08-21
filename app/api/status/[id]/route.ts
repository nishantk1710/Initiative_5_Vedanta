import { NextResponse } from "next/server";
import path from "path";
import { getProcessingProgress } from "@/lib/python-client";

export const runtime = "nodejs";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const safeId = path.basename(id);

  const progress = await getProcessingProgress(safeId);
  if (!progress) {
    return NextResponse.json(
      { error: `No progress recorded for document ${safeId}` },
      { status: 404 },
    );
  }
  return NextResponse.json(progress);
}
