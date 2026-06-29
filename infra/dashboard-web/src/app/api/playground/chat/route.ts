import { NextRequest } from "next/server";

const PLAYGROUND_URL =
  process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19390";

export async function POST(request: NextRequest) {
  const body = await request.text();

  const upstream = await fetch(`${PLAYGROUND_URL}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    // @ts-expect-error: Node fetch duplex
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(
      JSON.stringify({ error: `upstream ${upstream.status}` }),
      { status: 502, headers: { "content-type": "application/json" } }
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
