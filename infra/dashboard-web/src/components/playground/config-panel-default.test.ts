import { describe, expect, it } from "vitest";

describe("config-panel defaults", () => {
  it("initializes DEFAULT_CONFIG without module init errors", async () => {
    const mod = await import("./config-panel");
    expect(mod.DEFAULT_CONFIG.model).toBe("gpt-4o-mini");
    expect(new Date(mod.DEFAULT_CONFIG.asOfDate).toISOString()).toBe(mod.DEFAULT_CONFIG.asOfDate);
  });
});
