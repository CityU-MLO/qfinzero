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
    baseUrl: process.env.PMB_BASE_URL ?? "http://127.0.0.1:19701",
    healthPath: "/v1/health",
    statsPath: "/_stats",
    apiToken: process.env.PMB_API_TOKEN,
  },
  {
    name: "ESP",
    baseUrl: process.env.ESP_BASE_URL ?? "http://127.0.0.1:19702",
    healthPath: "/esp/health",
    statsPath: "/_stats",
    freshnessPath: "/esp/health/freshness",
    apiToken: process.env.ESP_API_TOKEN,
  },
  {
    name: "UPQ",
    baseUrl: process.env.UPQ_BASE_URL ?? "http://127.0.0.1:19703",
    healthPath: "/health",
    freshnessPath: "/health/freshness",
    apiToken: process.env.UPQ_API_TOKEN,
  },
];

export const ESP_BASE_URL = process.env.ESP_BASE_URL ?? "http://127.0.0.1:19702";
export const ESP_API_TOKEN = process.env.ESP_API_TOKEN;
export const STATUS_REFRESH_MS = Number(process.env.NEXT_PUBLIC_STATUS_REFRESH_MS ?? "15000");

export function extractPort(baseUrl: string): string | null {
  try {
    const url = new URL(baseUrl);
    return url.port || null;
  } catch {
    return null;
  }
}
