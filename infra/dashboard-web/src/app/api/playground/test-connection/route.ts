import { NextRequest } from "next/server";

const PLAYGROUND_URL =
  process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19704";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const upstream = await fetch(`${PLAYGROUND_URL}/test-connection`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
  const data = await upstream.json();
  return Response.json(data, { status: upstream.ok ? 200 : 502 });
}
