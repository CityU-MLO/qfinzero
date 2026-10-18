import { NextRequest } from "next/server";
import { identityHeaders } from "@/lib/identity";

const PLAYGROUND_URL =
  process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19390";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(`${PLAYGROUND_URL}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json", ...identityHeaders(request) },
    body,
    // @ts-expect-error: Node fetch duplex
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "");
    return new Response(
      JSON.stringify({ error: `upstream ${upstream.status}`, detail }),
      { status: upstream.status === 409 ? 409 : 502, headers: { "content-type": "application/json" } }
    );
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}
