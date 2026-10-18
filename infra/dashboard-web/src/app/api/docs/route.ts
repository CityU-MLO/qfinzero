import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

import { isLocale, type Locale } from "@/lib/i18n";
import type { DocIndex, DocPage } from "@/lib/docs";

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

export async function GET(req: Request) {
  const url = new URL(req.url);
  const index = await loadIndex();
  const pages: DocPage[] = index.sections.flatMap((s) => s.pages);

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
