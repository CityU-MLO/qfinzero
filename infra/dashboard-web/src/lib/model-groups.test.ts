import { describe, expect, it } from "vitest";

import { emptySettings, exportJson, mergeImport, migrateLegacy, parseImport, resolve } from "./model-groups";

const CLAUDE_CODE = JSON.stringify({
  $schema: "https://json.schemastore.org/claude-code-settings.json",
  env: { ANTHROPIC_BASE_URL: "http://gw.test:8081/antigravity", ANTHROPIC_AUTH_TOKEN: "sk-ag-test", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1" },
});

const EXPORTS = `export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_AUTH_TOKEN="sk-ant-test"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`;

const CODEX = `model_provider = "OpenAI"
model = "gpt-6"
disable_response_storage = true

[model_providers.OpenAI]
name = "OpenAI"
base_url = "http://gw.test:8081/v1"
wire_api = "responses"
experimental_bearer_token = "sk-oa-test"
http_headers = { "x-openai-actor-authorization" = "local-image-extension" }

[features]
goals = true
`;

describe("parseImport", () => {
  it("reads a Claude Code settings file as an Antigravity group", () => {
    const r = parseImport(CLAUDE_CODE);
    expect(r.source).toBe("claude-code");
    expect(r.groups).toEqual([
      { name: "Gemini · Antigravity · gw.test:8081", api: "antigravity", baseUrl: "http://gw.test:8081/antigravity", apiKey: "sk-ag-test", models: [] },
    ]);
  });

  it("reads shell export lines", () => {
    const r = parseImport(EXPORTS);
    expect(r.groups[0]).toMatchObject({ api: "anthropic", baseUrl: "https://api.anthropic.com", apiKey: "sk-ant-test" });
  });

  it("reads a Codex config.toml with its active model", () => {
    const r = parseImport(CODEX);
    expect(r.source).toBe("codex");
    expect(r.groups).toEqual([{ name: "OpenAI", api: "openai", baseUrl: "http://gw.test:8081/v1", apiKey: "sk-oa-test", models: [] }]);
    expect(r.active).toEqual({ group: "OpenAI", model: "gpt-6" });
  });

  it("round-trips its own export, with or without keys", () => {
    let s = mergeImport(emptySettings(), parseImport(CODEX));
    s = { ...s, groups: s.groups.map((g) => ({ ...g, models: [{ id: "gpt-6", name: "GPT-6" }] })) };
    const back = parseImport(exportJson(s, true));
    expect(back.groups[0]).toMatchObject({ api: "openai", apiKey: "sk-oa-test", models: [{ id: "gpt-6", name: "gpt-6" }] });
    expect(back.active).toEqual({ group: "OpenAI", model: "gpt-6" });
    expect(parseImport(exportJson(s, false)).groups[0].apiKey).toBe("");
  });

  it("rejects unknown input with a message", () => {
    expect(() => parseImport("")).toThrow("empty");
    expect(() => parseImport("{\"a\":1}")).toThrow("neither");
    expect(() => parseImport("hello")).toThrow("nothing recognised");
  });
});

describe("mergeImport", () => {
  it("updates a group with the same endpoint instead of duplicating it", () => {
    const a = mergeImport(emptySettings(), parseImport(CLAUDE_CODE));
    const again = parseImport(CLAUDE_CODE.replace("sk-ag-test", "sk-ag-new"));
    const b = mergeImport(a, again);
    expect(b.groups).toHaveLength(1);
    expect(b.groups[0].apiKey).toBe("sk-ag-new");
  });

  it("sets the active model and resolves it", () => {
    const s = mergeImport(emptySettings(), parseImport(CODEX));
    expect(resolve(s)).toMatchObject({ api: "openai", baseUrl: "http://gw.test:8081/v1", model: "gpt-6" });
  });
});

describe("migrateLegacy", () => {
  it("keeps configured providers and maps Claude to the Anthropic protocol", () => {
    const s = migrateLegacy({
      providers: [
        { id: "openai", label: "OpenAI (GPT)", baseUrl: "https://api.openai.com/v1", apiKey: "", models: ["gpt-4o"] },
        { id: "claude", label: "Claude", baseUrl: "https://api.anthropic.com/v1", apiKey: "k", models: ["claude-x"] },
      ],
      activeProviderId: "claude",
      activeModel: "claude-x",
      proxy: "",
    })!;
    expect(s.groups).toHaveLength(1);
    expect(s.groups[0]).toMatchObject({ api: "anthropic", baseUrl: "https://api.anthropic.com" });
    expect(s.active).toEqual({ groupId: "claude", model: "claude-x" });
  });
});
