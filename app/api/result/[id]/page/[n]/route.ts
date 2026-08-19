import { NextResponse } from "next/server";
import path from "path";

export const runtime = "nodejs";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://localhost:8000";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; n: string }> },
) {
  const { id, n } = await params;
  const safeId = path.basename(id);
  const pageNumber = Number(n);

  if (!Number.isInteger(pageNumber) || pageNumber < 1) {
    return NextResponse.json({ error: "Invalid page number" }, { status: 400 });
  }

  const upstream = await fetch(`${PYTHON_API_URL}/page/${safeId}/${pageNumber}`);

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { error: `Page image not found for document ${safeId}, page ${pageNumber}` },
      { status: upstream.status === 404 ? 404 : 502 },
    );
  }

  return new NextResponse(upstream.body, {
    headers: { "Content-Type": "image/png" },
  });
}
