import { NextRequest } from "next/server";

const PLAYGROUND_URL = process.env.PLAYGROUND_SERVICE_URL ?? "http://localhost:19390";

// List a provider group's models: {api, base_url, api_key, proxy?} -> {ok, models} | {ok:false, error}.
// The request goes server-side so the provider needs no CORS and the egress proxy applies.
export async function POST(request: NextRequest) {
  const body = await request.text();
  let upstream: Response;
  try {
    upstream = await fetch(`${PLAYGROUND_URL}/models`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  } catch (e) {
    return Response.json(
      { ok: false, error: `Playground service unreachable at ${PLAYGROUND_URL} (${(e as Error).message})` },
      { status: 502 },
    );
  }
  const text = await upstream.text();
  try {
    return Response.json(JSON.parse(text), { status: upstream.ok ? 200 : 502 });
  } catch {
    return Response.json(
      { ok: false, error: `Playground returned HTTP ${upstream.status}: ${text.slice(0, 200)}` },
      { status: 502 },
    );
  }
}
