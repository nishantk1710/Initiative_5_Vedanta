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
  const regionsPath = path.join(process.cwd(), "results", safeId, "regions.json");

  try {
    const raw = await readFile(regionsPath, "utf-8");
    return new NextResponse(raw, {
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json(
      { error: `No region data found for document ${safeId}` },
      { status: 404 },
    );
  }
}
