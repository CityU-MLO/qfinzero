import { NextRequest } from "next/server";

const PLAYGROUND_URL =
  process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19390";

export async function POST(request: NextRequest) {
  const body = await request.text();
  // The request body may carry an optional `proxy` field; it is forwarded verbatim
  // so the playground service routes the provider check through the LLM egress proxy.
  let upstream: Response;
  try {
    upstream = await fetch(`${PLAYGROUND_URL}/test-connection`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  } catch (e) {
    // Playground service unreachable — return JSON (not an empty 500) so the UI
    // shows a clear message instead of "Unexpected end of JSON input".
    return Response.json(
      { ok: false, error: `Playground service unreachable at ${PLAYGROUND_URL} (${(e as Error).message}). Is it running on :19390?` },
      { status: 502 },
    );
  }
  const text = await upstream.text();
  try {
    return Response.json(JSON.parse(text), { status: upstream.ok ? 200 : 502 });
  } catch {
    return Response.json(
      { ok: false, error: `Playground returned a non-JSON response (HTTP ${upstream.status}): ${text.slice(0, 200)}` },
      { status: 502 },
    );
  }
}
