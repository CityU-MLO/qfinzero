import { NextRequest, NextResponse } from "next/server";
import { DATA_ADMIN_BASE_URL } from "@/lib/config";

// Server-side proxy to the data-admin service (:19340) so the browser never needs
// its URL and SSE job-log streams pass straight through. Any /api/data-admin/<x>
// forwards to <DATA_ADMIN_BASE_URL>/<x> preserving method, query, and body.

export const dynamic = "force-dynamic";

async function forward(req: NextRequest, path: string[]): Promise<Response> {
  const search = req.nextUrl.search ?? "";
  const target = `${DATA_ADMIN_BASE_URL}/${path.join("/")}${search}`;
  const init: RequestInit = {
    method: req.method,
    headers: { "content-type": req.headers.get("content-type") ?? "application/json" },
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }
  try {
    const res = await fetch(target, init);
    // Stream SSE (job logs) straight through, unbuffered.
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("text/event-stream")) {
      return new Response(res.body, {
        status: res.status,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          "x-accel-buffering": "no",
        },
      });
    }
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: { "content-type": ct || "application/json" },
    });
  } catch (e) {
    return NextResponse.json(
      { error: `data-admin unreachable at ${DATA_ADMIN_BASE_URL}: ${String(e)}` },
      { status: 502 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
