import { NextResponse } from "next/server";

import { nppSanity } from "@/lib/api";

export async function GET() {
  try {
    const data = await nppSanity();
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
