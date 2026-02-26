import { describe, expect, it } from "vitest";

import { buildCoverageHeatmap } from "@/lib/coverage";

describe("buildCoverageHeatmap", () => {
  it("builds date buckets with zero-filled gaps", () => {
    const cells = buildCoverageHeatmap(
      [
        { date: "2026-02-10", count: 3 },
        { date: "2026-02-12", count: 7 },
      ],
      "2026-02-10",
      "2026-02-12",
    );

    expect(cells).toEqual([
      { date: "2026-02-10", count: 3 },
      { date: "2026-02-11", count: 0 },
      { date: "2026-02-12", count: 7 },
    ]);
  });
});
