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
