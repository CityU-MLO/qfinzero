import type { ServiceName } from "@/lib/types";

export type ServiceConfig = {
  name: ServiceName;
  baseUrl: string;
  healthPath: string;
  statsPath?: string;
  freshnessPath?: string;
  apiToken?: string;
};

export const SERVICES: ServiceConfig[] = [
  {
    name: "PMB",
    baseUrl: process.env.PMB_BASE_URL ?? "http://127.0.0.1:19320",
    healthPath: "/v1/health",
    statsPath: "/_stats",
    apiToken: process.env.PMB_API_TOKEN,
  },
  {
    name: "NPP",
    baseUrl: process.env.NPP_BASE_URL ?? "http://127.0.0.1:19330",
    healthPath: "/npp/health",
    statsPath: "/_stats",
    freshnessPath: "/npp/health/freshness",
    apiToken: process.env.NPP_API_TOKEN,
  },
  {
    name: "UPQ",
    baseUrl: process.env.UPQ_BASE_URL ?? "http://127.0.0.1:19350",
    healthPath: "/health",
    freshnessPath: "/health/freshness",
    apiToken: process.env.UPQ_API_TOKEN,
  },
];

export const NPP_BASE_URL = process.env.NPP_BASE_URL ?? "http://127.0.0.1:19330";
export const NPP_API_TOKEN = process.env.NPP_API_TOKEN;
export const STATUS_REFRESH_MS = Number(process.env.NEXT_PUBLIC_STATUS_REFRESH_MS ?? "15000");

export function extractPort(baseUrl: string): string | null {
  try {
    const url = new URL(baseUrl);
    return url.port || null;
  } catch {
    return null;
  }
}
