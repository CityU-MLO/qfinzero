import { NextResponse } from "next/server";

// Surface locally-configured API keys (from .env.local / process env) to the
// Settings page so it can pre-fill provider keys. Server-side only; not bundled.
export async function GET() {
  const keys: Record<string, string> = {
    openai: process.env.OPENAI_API_KEY ?? "",
    deepseek: process.env.DEEPSEEK_API_KEY ?? "",
    gemini: process.env.GEMINI_API_KEY ?? "",
    claude: process.env.ANTHROPIC_API_KEY ?? process.env.CLAUDE_API_KEY ?? "",
  };
  // also report which are present (handy for a "loaded" indicator)
  const loaded = Object.fromEntries(Object.entries(keys).map(([k, v]) => [k, Boolean(v)]));
  // Whether the server has an LLM egress proxy configured (presence only — the value
  // is applied server-side, so creds never reach the browser). UI shows an indicator
  // and lets the user override per request.
  const proxyLoaded = Boolean(
    process.env.LLM_PROXY || process.env.HTTPS_PROXY || process.env.HTTP_PROXY,
  );
  return NextResponse.json({ keys, loaded, proxyLoaded });
}
