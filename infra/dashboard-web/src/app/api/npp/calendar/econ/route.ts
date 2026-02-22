import { NextResponse } from "next/server";

import { nppCalendarEconomic } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    const data = await nppCalendarEconomic(payload);
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "calendar_econ_failed",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
