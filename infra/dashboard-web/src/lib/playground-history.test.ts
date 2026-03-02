import { beforeEach, describe, expect, it } from "vitest";

import {
  appendThreadMessage,
  deriveThreadTitleFromMessage,
  loadThreadMessages,
  loadThreads,
  upsertThread,
} from "@/lib/playground-history";

describe("playground-history", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists thread metadata and can load it back", () => {
    upsertThread({
      id: "thread-1",
      title: "Greeks analysis",
      status: "regular",
      createdAt: "2026-03-02T00:00:00.000Z",
      updatedAt: "2026-03-02T00:00:00.000Z",
    });

    const threads = loadThreads();
    expect(threads).toHaveLength(1);
    expect(threads[0]?.id).toBe("thread-1");
    expect(threads[0]?.title).toBe("Greeks analysis");
  });

  it("appends and reloads thread messages", () => {
    appendThreadMessage("thread-2", {
      id: "m1",
      role: "user",
      content: [{ type: "text", text: "hello" }],
      createdAt: "2026-03-02T00:00:00.000Z",
    });

    const messages = loadThreadMessages("thread-2");
    expect(messages).toHaveLength(1);
    expect(messages[0]?.id).toBe("m1");
  });

  it("derives a compact title from first user text", () => {
    const title = deriveThreadTitleFromMessage({
      role: "user",
      content: [{ type: "text", text: "Explain spread max loss and breakeven formula quickly" }],
    });

    expect(title).toMatch(/Explain spread max loss/i);
  });
});
