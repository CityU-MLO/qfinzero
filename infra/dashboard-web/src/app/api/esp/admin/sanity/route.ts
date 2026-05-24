import { NextResponse } from "next/server";

import { espSanity } from "@/lib/api";

export async function GET() {
  try {
    const data = await espSanity();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "sanity_failed",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
