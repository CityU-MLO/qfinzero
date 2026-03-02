import { describe, expect, it } from "vitest";

import {
  createPlaygroundStreamState,
  parsePlaygroundSseLine,
  reducePlaygroundSseEvent,
} from "@/lib/playground-stream";

describe("playground-stream reducer", () => {
  it("parses SSE json payload", () => {
    const event = parsePlaygroundSseLine(
      'data: {"type":"tool_start","tool":"upq_option_chain","input":{"underlying":"NVDA"}}'
    );

    expect(event).toBeTruthy();
    expect(event?.type).toBe("tool_start");
    expect(event?.tool).toBe("upq_option_chain");
  });

  it("tracks tool lifecycle from start to end", () => {
    let state = createPlaygroundStreamState();

    state = reducePlaygroundSseEvent(
      state,
      { type: "tool_start", tool: "upq_option_chain", input: { underlying: "NVDA" } },
      () => "call-1"
    );

    expect(state.toolCalls).toHaveLength(1);
    expect(state.toolCalls[0]?.status).toBe("loading");

    state = reducePlaygroundSseEvent(
      state,
      { type: "tool_end", tool: "upq_option_chain", output: { rows: 123 } },
      () => "call-x"
    );

    expect(state.toolCalls[0]?.status).toBe("done");
    expect(state.toolCalls[0]?.output).toEqual({ rows: 123 });
  });

  it("accumulates llm chunks", () => {
    let state = createPlaygroundStreamState();

    state = reducePlaygroundSseEvent(state, { type: "llm_chunk", content: "| a | b |\n" }, () => "x");
    state = reducePlaygroundSseEvent(state, { type: "llm_chunk", content: "|---|---|\n" }, () => "x");

    expect(state.text).toBe("| a | b |\n|---|---|\n");
  });
});
