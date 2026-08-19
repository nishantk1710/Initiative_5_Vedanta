import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import path from "path";

export const runtime = "nodejs";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const safeId = path.basename(id);
  const resultPath = path.join(process.cwd(), "results", safeId, "result.json");

  try {
    const raw = await readFile(resultPath, "utf-8");
    return new NextResponse(raw, {
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json(
      { error: `No result found for document ${safeId}` },
      { status: 404 },
    );
  }
}
