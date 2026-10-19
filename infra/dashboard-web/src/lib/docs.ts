// Types of the documentation hub index (docs/index.json) and page payloads.

export type Localized = { en: string; zh: string };

export interface DocPage {
  slug: string;
  title: Localized;
  en: string;
  zh?: string;
  available?: { en: boolean; zh: boolean };
}

export interface DocSection {
  id: string;
  title: Localized;
  pages: DocPage[];
}

export interface DocIndex {
  sections: DocSection[];
}

export interface DocContent {
  slug: string;
  title: Localized;
  lang: "en" | "zh";
  fallback: boolean;
  source: string;
  content: string;
  prev: { slug: string; title: Localized } | null;
  next: { slug: string; title: Localized } | null;
}

/** Heading text -> anchor id (GitHub style, keeps CJK characters). */
export function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[`*~]/g, "")
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .replace(/\s/g, "-");
}

/** ``## `` and ``### `` headings of a markdown document, outside code fences. */
export function headings(md: string): { level: 2 | 3; text: string; id: string }[] {
  const out: { level: 2 | 3; text: string; id: string }[] = [];
  let fence = false;
  for (const line of md.split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence;
    if (fence) continue;
    const m = /^(##|###)\s+(.+?)\s*#*\s*$/.exec(line);
    if (m) {
      const text = m[2].replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
      out.push({ level: m[1].length as 2 | 3, text, id: slugify(text) });
    }
  }
  return out;
}

// ── API reference (docs/api/reference.json, built by `python -m qfinzero.docsgen`) ──

export interface ApiField {
  name: string;
  type: string;
  required: boolean;
  description: string;
  in?: "query" | "path" | "header" | "cookie";
  default?: unknown;
  enum?: unknown[];
  example?: unknown;
  nullable?: boolean;
  range?: [number | null, number | null];
  children?: ApiField[];
}

export interface ApiEndpoint {
  id: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  group: string;
  summary: string;
  description: string;
  params: ApiField[];
  body: { fields: ApiField[]; required: boolean; example: unknown } | null;
  responses: { status: string; description: string; example?: unknown }[];
  deprecated: boolean;
}

export interface ApiService {
  id: string;
  title: Localized;
  summary: Localized;
  base: string;
  scope: string;
  version: string;
  intro: string;
  endpoints: ApiEndpoint[];
}

export interface McpTool {
  name: string;
  group: string;
  summary: string;
  description: string;
  params: ApiField[];
  returns: string;
  example: Record<string, unknown>;
}

export interface ApiReference {
  services: ApiService[];
  mcp: McpTool[];
}

/** One searchable entry: a guide section, an endpoint or an MCP tool. */
export interface SearchEntry {
  kind: "guide" | "endpoint" | "tool";
  href: string;
  title: string;
  section: string;
  text: string;
}

/** Group items by a key, keeping first-seen order. */
export function groupBy<T>(items: T[], key: (x: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  for (const x of items) {
    const k = key(x);
    m.set(k, [...(m.get(k) ?? []), x]);
  }
  return [...m.entries()];
}

/** Score an entry for a query (0 = no match): every word must appear somewhere. */
export function scoreEntry(e: SearchEntry, words: string[]): number {
  const title = e.title.toLowerCase();
  const sect = e.section.toLowerCase();
  const text = e.text.toLowerCase();
  let score = 0;
  for (const w of words) {
    if (title === w) score += 12;
    else if (title.startsWith(w)) score += 8;
    else if (title.includes(w)) score += 5;
    else if (sect.includes(w)) score += 2;
    else if (text.includes(w)) score += 1;
    else return 0;
  }
  return score + (e.kind === "guide" ? 0.5 : 0);
}

/** A short excerpt of ``text`` around the first query word. */
export function excerpt(text: string, words: string[], width = 140): string {
  const low = text.toLowerCase();
  const at = Math.min(...words.map((w) => low.indexOf(w)).filter((i) => i >= 0), Infinity);
  if (!Number.isFinite(at)) return text.slice(0, width);
  const start = Math.max(0, at - 40);
  return (start > 0 ? "…" : "") + text.slice(start, start + width).trim() + (start + width < text.length ? "…" : "");
}
