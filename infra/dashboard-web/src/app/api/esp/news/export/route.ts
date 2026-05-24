import { proxyExport } from "@/lib/api";

export async function GET(request: Request) {
  const { search } = new URL(request.url);
  return proxyExport(`/esp/news/export${search}`, request);
}
