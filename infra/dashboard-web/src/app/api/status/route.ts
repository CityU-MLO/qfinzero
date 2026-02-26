import { NextResponse } from "next/server";

import { getStatusSummary } from "@/lib/api";

export async function GET() {
  try {
    const data = await getStatusSummary();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "status_unavailable",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 503 },
    );
  }
}
