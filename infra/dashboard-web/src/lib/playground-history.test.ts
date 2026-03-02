import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import {
  appendThreadMessage,
  deriveThreadTitleFromMessage,
  loadThreadMessages,
  loadThreads,
  upsertThread,
} from "@/lib/playground-history";

function createMockStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear() {
      map.clear();
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null;
    },
    key(index: number) {
      const keys = Array.from(map.keys());
      return keys[index] ?? null;
    },
    removeItem(key: string) {
      map.delete(key);
    },
    setItem(key: string, value: string) {
      map.set(key, value);
    },
  };
}

describe("playground-history", () => {
  const originalLocalStorage = window.localStorage;

  beforeAll(() => {
    Object.defineProperty(window, "localStorage", {
      value: createMockStorage(),
      configurable: true,
    });
  });

  beforeEach(() => {
    window.localStorage.clear();
  });

  afterAll(() => {
    Object.defineProperty(window, "localStorage", {
      value: originalLocalStorage,
      configurable: true,
    });
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
