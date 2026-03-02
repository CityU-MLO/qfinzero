export type PlaygroundToolCallStatus = "loading" | "done" | "error";

export interface PlaygroundToolCall {
  id: string;
  tool: string;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  status: PlaygroundToolCallStatus;
}

export interface PlaygroundSseEvent {
  type?: string;
  tool?: string;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  message?: string;
  content?: string;
}

export interface PlaygroundStreamState {
  text: string;
  toolCalls: PlaygroundToolCall[];
  pendingByTool: Record<string, string[]>;
}

export function createPlaygroundStreamState(): PlaygroundStreamState {
  return {
    text: "",
    toolCalls: [],
    pendingByTool: {},
  };
}

export function parsePlaygroundSseLine(line: string): PlaygroundSseEvent | null {
  if (!line.startsWith("data: ")) return null;
  const raw = line.slice(6).trim();
  if (!raw) return null;

  try {
    return JSON.parse(raw) as PlaygroundSseEvent;
  } catch {
    return null;
  }
}

export function reducePlaygroundSseEvent(
  state: PlaygroundStreamState,
  event: PlaygroundSseEvent,
  makeId: () => string
): PlaygroundStreamState {
  const type = event.type;

  if (type === "llm_chunk") {
    return {
      ...state,
      text: state.text + (event.content ?? ""),
    };
  }

  if (type === "tool_start") {
    const toolName = event.tool;
    if (!toolName) return state;

    const callId = makeId();
    return {
      ...state,
      toolCalls: [
        ...state.toolCalls,
        {
          id: callId,
          tool: toolName,
          input: event.input,
          status: "loading",
        },
      ],
      pendingByTool: {
        ...state.pendingByTool,
        [toolName]: [...(state.pendingByTool[toolName] ?? []), callId],
      },
    };
  }

  if (type === "tool_end") {
    const toolName = event.tool;
    if (!toolName) return state;

    const queue = state.pendingByTool[toolName] ?? [];
    const callId = queue[0];
    if (!callId) return state;

    return {
      ...state,
      toolCalls: state.toolCalls.map((call) =>
        call.id === callId
          ? {
              ...call,
              status: event.error ? "error" : "done",
              output: event.output,
              error: event.error,
            }
          : call
      ),
      pendingByTool: {
        ...state.pendingByTool,
        [toolName]: queue.slice(1),
      },
    };
  }

  return state;
}
