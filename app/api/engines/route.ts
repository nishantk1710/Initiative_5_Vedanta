import { NextResponse } from "next/server";
import { listEngines } from "@/lib/python-client";

export const runtime = "nodejs";

export async function GET() {
  try {
    const engines = await listEngines();
    return NextResponse.json({ engines });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to load engines" },
      { status: 502 },
    );
  }
}
