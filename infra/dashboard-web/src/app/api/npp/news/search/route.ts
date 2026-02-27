import { NextResponse } from "next/server";

import { nppSearchNews } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    const data = await nppSearchNews(payload);
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "news_search_failed",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
