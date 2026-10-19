import { describe, expect, it } from "vitest";

import { excerpt, groupBy, headings, scoreEntry, slugify, type SearchEntry } from "./docs";

const e = (title: string, text = "", section = "Guides", kind: SearchEntry["kind"] = "guide"): SearchEntry =>
  ({ kind, href: "/docs/x", title, section, text });

describe("doc search", () => {
  it("needs every word and ranks titles above body text", () => {
    const words = ["api", "key"];
    expect(scoreEntry(e("API keys"), words)).toBeGreaterThan(scoreEntry(e("Accounts", "create an api key here"), words));
    expect(scoreEntry(e("API keys", ""), ["api", "budget"])).toBe(0);
  });

  it("excerpts around the first match", () => {
    const text = "a ".repeat(100) + "monthly budget per key " + "b ".repeat(100);
    const x = excerpt(text, ["budget"]);
    expect(x.startsWith("…")).toBe(true);
    expect(x).toContain("budget");
  });

  it("groups in first-seen order", () => {
    expect(groupBy([{ g: "b" }, { g: "a" }, { g: "b" }], (x) => x.g).map(([k, v]) => [k, v.length])).toEqual([["b", 2], ["a", 1]]);
  });

  it("anchors match the headings of the page", () => {
    expect(slugify("Handing out API keys")).toBe("handing-out-api-keys");
    expect(headings("# T\n## 1. Time lock\n```\n## not a heading\n```\n### 分发 API key").map((h) => h.id))
      .toEqual(["1-time-lock", "分发-api-key"]);
  });
});
