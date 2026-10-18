import { NextResponse, type NextRequest } from "next/server";

// Which LLM provider keys the server has configured. Key values are returned
// only to admins (the hub verifies the caller and sets x-qfz-role); everyone
// else sees presence flags, so a key never reaches a non-admin browser.
export async function GET(req: NextRequest) {
  const raw: Record<string, string> = {
    openai: process.env.OPENAI_API_KEY ?? "",
    deepseek: process.env.DEEPSEEK_API_KEY ?? "",
    gemini: process.env.GEMINI_API_KEY ?? "",
    claude: process.env.ANTHROPIC_API_KEY ?? process.env.CLAUDE_API_KEY ?? "",
  };
  const isAdmin = req.headers.get("x-qfz-role") === "admin";
  const keys = Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, isAdmin ? v : ""]));
  const loaded = Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, Boolean(v)]));
  // LLM egress proxy presence only; the value is applied server-side.
  const proxyLoaded = Boolean(
    process.env.LLM_PROXY || process.env.HTTPS_PROXY || process.env.HTTP_PROXY,
  );
  return NextResponse.json({ keys, loaded, proxyLoaded });
}
