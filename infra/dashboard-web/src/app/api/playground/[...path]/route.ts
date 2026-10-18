import { NextRequest, NextResponse } from "next/server";
import { identityHeaders } from "@/lib/identity";

// Proxy to the playground service for conversations: /api/playground/threads/...
// Streams are passed through (chat itself goes through ../chat).
const PLAYGROUND_URL = process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19390";
export const dynamic = "force-dynamic";

async function forward(req: NextRequest, path: string[]): Promise<Response> {
  const target = `${PLAYGROUND_URL}/${path.join("/")}${req.nextUrl.search ?? ""}`;
  const init: RequestInit = {
    method: req.method,
    headers: { "content-type": req.headers.get("content-type") ?? "application/json", ...identityHeaders(req) },
  };
  if (req.method !== "GET" && req.method !== "HEAD") init.body = await req.text();
  try {
    const res = await fetch(target, init);
    const headers: Record<string, string> = { "content-type": res.headers.get("content-type") ?? "application/json" };
    const cd = res.headers.get("content-disposition");
    if (cd) headers["content-disposition"] = cd;
    return new Response(res.body, { status: res.status, headers });
  } catch (e) {
    return NextResponse.json({ detail: `playground unreachable at ${PLAYGROUND_URL}: ${String(e)}` }, { status: 502 });
  }
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function POST(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function PATCH(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function DELETE(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
