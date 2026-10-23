import { describe, expect, it } from "vitest";

import { applyEvent, type ChatMessage } from "./chat-api";

const live = (): ChatMessage => ({ id: "live", role: "assistant", content: "", steps: [], status: "running", created_at: 0 });

describe("applyEvent", () => {
  it("shows a retry and drops the failed attempt's partial text", () => {
    let m = live();
    m = applyEvent(m, { type: "step_start", step: 0, t: 1 });
    m = applyEvent(m, { type: "llm_chunk", step: 0, content: "half an ans" });
    m = applyEvent(m, { type: "retry", step: 0, attempt: 1, of: 4, delay_s: 6, error: "overloaded", t: 2 });
    expect(m.steps[0].retry).toMatchObject({ attempt: 1, of: 4, delay_s: 6 });
    m = applyEvent(m, { type: "step_start", step: 0, t: 8, restart: true });
    expect(m.steps[0].text).toBe("");
    m = applyEvent(m, { type: "llm_chunk", step: 0, content: "Whole answer." });
    m = applyEvent(m, { type: "step_end", step: 0, t: 9, text: "Whole answer.", tool_calls: [] });
    expect(m.steps).toHaveLength(1);
    expect(m.steps[0]).toMatchObject({ text: "Whole answer.", retry: null, retries: 1 });
    expect(m.content).toBe("Whole answer.");
  });
});
