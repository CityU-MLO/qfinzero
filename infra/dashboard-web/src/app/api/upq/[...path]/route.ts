import { NextRequest, NextResponse } from "next/server";

// Server-side proxy to the UPQ market-data service (:19350) — e.g.
// /api/upq/option/chain_query?underlying=AAPL&date=2024-03-22
const UPQ_BASE_URL = process.env.UPQ_BASE_URL ?? "http://127.0.0.1:19350";
export const dynamic = "force-dynamic";

async function forward(req: NextRequest, path: string[]): Promise<Response> {
  const target = `${UPQ_BASE_URL}/${path.join("/")}${req.nextUrl.search ?? ""}`;
  const init: RequestInit = {
    method: req.method,
    headers: { "content-type": req.headers.get("content-type") ?? "application/json" },
  };
  if (req.method !== "GET" && req.method !== "HEAD") init.body = await req.text();
  try {
    const res = await fetch(target, init);
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch (e) {
    return NextResponse.json(
      { error: `upq unreachable at ${UPQ_BASE_URL}: ${String(e)}` },
      { status: 502 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
