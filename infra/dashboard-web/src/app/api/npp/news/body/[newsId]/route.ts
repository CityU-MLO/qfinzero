import { NextResponse } from "next/server";

import { nppNewsBody } from "@/lib/api";

type Params = {
  params: Promise<{ newsId: string }>;
};

export async function GET(_request: Request, { params }: Params) {
  const { newsId } = await params;

  try {
    const data = await nppNewsBody(newsId);
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      {
        code: "news_body_failed",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
