import { describe, expect, it } from "vitest";

import { normalizeMathDelimiters } from "@/lib/playground-math";

describe("normalizeMathDelimiters", () => {
  it("converts inline and block latex delimiters to dollar style", () => {
    const input = String.raw`Inline: \(a+b\), Block: \[x^2+y^2\]`;
    const normalized = normalizeMathDelimiters(input);

    expect(normalized).toContain("Inline: $a+b$");
    expect(normalized).toContain("Block: $$x^2+y^2$$");
  });

  it("handles double-escaped delimiters often seen in streamed responses", () => {
    const input = String.raw`\\(Delta\\) and \\[Gamma\\]`;
    const normalized = normalizeMathDelimiters(input);

    expect(normalized).toContain("$Delta$");
    expect(normalized).toContain("$$Gamma$$");
  });
});
