import { NextRequest, NextResponse } from "next/server";

import { DATA_ADMIN_BASE_URL } from "@/lib/config";
import { identityHeaders } from "@/lib/identity";

// Read-only coverage map backed by the data-admin service. Unlike the rest of
// /api/data-admin (admins only) every signed-in user may read it.
export const dynamic = "force-dynamic";

const ALLOWED = new Set(["extent", "matrix", "cell", "suggest", "days", "day"]);

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (path.length !== 1 || !ALLOWED.has(path[0])) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  try {
    const res = await fetch(`${DATA_ADMIN_BASE_URL}/coverage/${path[0]}${req.nextUrl.search ?? ""}`, {
      headers: identityHeaders(req),
      cache: "no-store",
    });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch (e) {
    return NextResponse.json({ error: `data service unreachable: ${String(e)}` }, { status: 502 });
  }
}
