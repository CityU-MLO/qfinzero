import { NextRequest, NextResponse } from "next/server";

// Server-side proxy to the PMB service (:19380) — e.g. /api/pmb/v1/config.
const PMB_BASE_URL = process.env.PMB_BASE_URL ?? "http://127.0.0.1:19380";
export const dynamic = "force-dynamic";

async function forward(req: NextRequest, path: string[]): Promise<Response> {
  const target = `${PMB_BASE_URL}/${path.join("/")}${req.nextUrl.search ?? ""}`;
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
      { error: `pmb unreachable at ${PMB_BASE_URL}: ${String(e)}` },
      { status: 502 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function POST(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function PUT(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
