import { NextResponse } from "next/server";
import path from "path";
import { compareEngines } from "@/lib/python-client";

export const runtime = "nodejs";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; page: string }> },
) {
  const { id, page } = await params;
  const safeId = path.basename(id);
  const pageNumber = Number(page);

  if (!Number.isInteger(pageNumber) || pageNumber < 1) {
    return NextResponse.json({ error: "Invalid page number" }, { status: 400 });
  }

  const engines = new URL(request.url).searchParams.get("engines");
  const engineList = engines ? engines.split(",").map((e) => e.trim()) : undefined;

  try {
    const result = await compareEngines(safeId, pageNumber, engineList);
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Comparison failed" },
      { status: 502 },
    );
  }
}
