import { NextResponse } from "next/server";

import { nppCalendarEarnings } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    const data = await nppCalendarEarnings(payload);
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "calendar_earnings_failed",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
