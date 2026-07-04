import { NextResponse, type NextRequest } from "next/server";

import { LEGACY_PREFIX, SKIN_HEADER, SKIN_LEGACY } from "@/lib/legacy";

// The hidden Windows-98 skin lives at the /legacy URL prefix. We keep the URL the user
// typed (/legacy, /legacy/data, …) but internally rewrite it to the real page (/,
// /data, …) and tag the request with x-ui-skin=legacy so the root layout knows to apply
// the retro skin. No redirect — the address bar stays at /legacy.
export function middleware(req: NextRequest) {
  const rest = req.nextUrl.pathname.slice(LEGACY_PREFIX.length) || "/";
  const url = req.nextUrl.clone();
  url.pathname = rest;

  const headers = new Headers(req.headers);
  headers.set(SKIN_HEADER, SKIN_LEGACY);
  return NextResponse.rewrite(url, { request: { headers } });
}

export const config = {
  matcher: ["/legacy", "/legacy/:path*"],
};
