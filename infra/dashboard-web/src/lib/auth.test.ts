import { describe, expect, it } from "vitest";

import { safeNext } from "./auth";
import { identityHeaders } from "./identity";

describe("safeNext", () => {
  it("keeps same-site paths", () => {
    expect(safeNext("/broker?x=1")).toBe("/broker?x=1");
  });
  it("refuses open redirects and loops", () => {
    expect(safeNext("https://evil.example")).toBe("/chat");
    expect(safeNext("//evil.example")).toBe("/chat");
    expect(safeNext("/login?next=/x")).toBe("/chat");
    expect(safeNext(null)).toBe("/chat");
  });
});

describe("identityHeaders", () => {
  it("forwards only the hub identity headers", () => {
    const req = new Request("http://x/", {
      headers: { "x-qfz-user": "ann", "x-qfz-role": "researcher", cookie: "secret", authorization: "Bearer k" },
    });
    expect(identityHeaders(req)).toEqual({ "x-qfz-user": "ann", "x-qfz-role": "researcher" });
  });
});
