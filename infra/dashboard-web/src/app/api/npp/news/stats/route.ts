import { NextResponse } from "next/server";

import { nppNewsStats } from "@/lib/api";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const days = Number(searchParams.get("days") ?? "7");
  try {
    const data = await nppNewsStats(Number.isFinite(days) ? days : 7);
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "news_stats_failed",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
