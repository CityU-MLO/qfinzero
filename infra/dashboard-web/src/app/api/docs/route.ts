import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

import { isLocale, type Locale } from "@/lib/i18n";
import { headings, type ApiReference, type DocIndex, type DocPage, type SearchEntry } from "@/lib/docs";

// Repo root relative to the Next process cwd (infra/dashboard-web).
const REPO_ROOT = path.resolve(process.cwd(), "../../");
const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/CityU-MLO/qfinzero";

async function loadIndex(): Promise<DocIndex> {
  const raw = JSON.parse(await fs.readFile(path.join(REPO_ROOT, "docs", "index.json"), "utf8"));
  return { sections: raw.sections };
}

async function exists(rel: string | undefined): Promise<boolean> {
  if (!rel) return false;
  try {
    await fs.access(path.join(REPO_ROOT, rel));
    return true;
  } catch {
    return false;
  }
}

/** Rewrite relative links: docs in the index → /docs/<slug>, anything else → the repository. */
function rewriteLinks(md: string, file: string, bySource: Map<string, string>): string {
  const dir = path.posix.dirname(file);
  return md.replace(/(!?)\[([^\]]*)\]\(([^)\s]+)((?:\s+"[^"]*")?)\)/g, (whole, bang, text, target, title) => {
    if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("#") || target.startsWith("/")) return whole;
    const [p, anchor] = target.split("#");
    const resolved = path.posix.normalize(path.posix.join(dir, p));
    if (resolved.startsWith("..")) return whole;
    const slug = bySource.get(resolved);
    if (slug && !bang) return `[${text}](/docs/${slug}${anchor ? `#${anchor}` : ""}${title})`;
    const kind = bang ? "raw" : "blob";
    return `${bang}[${text}](${REPO_URL}/${kind}/main/${resolved}${anchor ? `#${anchor}` : ""}${title})`;
  });
}

/** Drop the "> English: …" / "> 中文: …" switch lines; the hub has its own language switch. */
function stripLanguageSwitch(md: string): string {
  const lines = md.split("\n");
  const head = lines.slice(0, 8).filter((l) => !/^>\s*(English|中文)\s*[:：]/.test(l));
  return [...head, ...lines.slice(8)].join("\n").replace(/^\s+/, "");
}

async function loadReference(): Promise<ApiReference> {
  try {
    const raw = JSON.parse(await fs.readFile(path.join(REPO_ROOT, "docs", "api", "reference.json"), "utf8"));
    return { services: raw.services ?? [], mcp: raw.mcp ?? [] };
  } catch {
    return { services: [], mcp: [] };
  }
}

/** Markdown to searchable plain text. */
function plain(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[`*_>#|]/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Guide pages split at their ## / ### headings, plus endpoints and tools. */
async function searchIndex(index: DocIndex, lang: Locale): Promise<SearchEntry[]> {
  const out: SearchEntry[] = [];
  for (const s of index.sections) {
    for (const p of s.pages) {
      const file = lang === "zh" && (await exists(p.zh)) ? p.zh! : p.en;
      let md = "";
      try {
        md = stripLanguageSwitch(await fs.readFile(path.join(REPO_ROOT, file), "utf8"));
      } catch {
        continue;
      }
      const title = lang === "zh" ? p.title.zh : p.title.en;
      const section = lang === "zh" ? s.title.zh : s.title.en;
      const hs = headings(md);
      const lines = md.split("\n");
      // body before the first heading belongs to the page itself
      let cur = { title, id: "", buf: [] as string[] };
      const flush = () => {
        const text = plain(cur.buf.join("\n")).slice(0, 1200);
        if (text || !cur.id) out.push({ kind: "guide", href: `/docs/${p.slug}${cur.id ? `#${cur.id}` : ""}`,
          title: cur.title, section: cur.id ? `${section} › ${title}` : section, text });
      };
      let hi = 0;
      let fence = false;
      for (const line of lines) {
        if (/^\s*(```|~~~)/.test(line)) fence = !fence;
        if (!fence && /^(##|###)\s+/.test(line) && hi < hs.length) {
          flush();
          cur = { title: hs[hi].text, id: hs[hi].id, buf: [] };
          hi += 1;
          continue;
        }
        cur.buf.push(line);
      }
      flush();
    }
  }
  const ref = await loadReference();
  for (const svc of ref.services) {
    const st = lang === "zh" ? svc.title.zh : svc.title.en;
    for (const e of svc.endpoints) {
      out.push({ kind: "endpoint", href: `/docs/api/${svc.id}/${e.id}`, title: `${e.method} ${e.path}`,
        section: `${st} › ${e.group}`, text: `${e.summary}. ${e.description} ${e.params.map((x) => x.name).join(" ")}`.slice(0, 600) });
    }
  }
  for (const t of ref.mcp) {
    out.push({ kind: "tool", href: `/docs/mcp/${t.name}`, title: t.name, section: `MCP › ${t.group}`,
      text: `${t.summary} ${t.params.map((x) => x.name).join(" ")}`.slice(0, 600) });
  }
  return out;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const index = await loadIndex();
  const pages: DocPage[] = index.sections.flatMap((s) => s.pages);

  if (url.searchParams.get("ref")) return NextResponse.json(await loadReference());
  if (url.searchParams.get("search")) {
    const lang: Locale = isLocale(url.searchParams.get("lang")) ? (url.searchParams.get("lang") as Locale) : "en";
    return NextResponse.json({ entries: await searchIndex(index, lang) });
  }

  const slug = url.searchParams.get("slug");
  if (!slug) {
    // table of contents, with which languages each page exists in
    const sections = await Promise.all(
      index.sections.map(async (s) => ({
        ...s,
        pages: await Promise.all(
          s.pages.map(async (p) => ({ ...p, available: { en: await exists(p.en), zh: await exists(p.zh) } })),
        ),
      })),
    );
    return NextResponse.json({ sections });
  }

  const i = pages.findIndex((p) => p.slug === slug);
  if (i < 0) return NextResponse.json({ error: "not found" }, { status: 404 });
  const page = pages[i];
  const wanted: Locale = isLocale(url.searchParams.get("lang")) ? (url.searchParams.get("lang") as Locale) : "en";
  const lang: Locale = wanted === "zh" && (await exists(page.zh)) ? "zh" : "en";
  const file = (lang === "zh" ? page.zh : page.en) as string;

  const bySource = new Map<string, string>();
  for (const p of pages) {
    bySource.set(p.en, p.slug);
    if (p.zh) bySource.set(p.zh, p.slug);
  }
  let content: string;
  try {
    content = await fs.readFile(path.join(REPO_ROOT, file), "utf8");
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  content = rewriteLinks(stripLanguageSwitch(content), file, bySource);
  const nav = (p: DocPage | undefined) => (p ? { slug: p.slug, title: p.title } : null);
  return NextResponse.json({
    slug,
    title: page.title,
    lang,
    fallback: lang !== wanted,
    source: `${REPO_URL}/blob/main/${file}`,
    content,
    prev: nav(pages[i - 1]),
    next: nav(pages[i + 1]),
  });
}
