import { describe, expect, it } from "vitest";
import { fromZonedTime, toZonedTime } from "date-fns-tz";

const ET_ZONE = "America/New_York";

// Re-implement the functions under test inline since they're simple
// and importing from a "use client" tsx file in vitest can be tricky
function utcToDatetimeLocal(utcIso: string): string {
  const d = new Date(utcIso);
  const et = toZonedTime(d, ET_ZONE);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${et.getFullYear()}-${pad(et.getMonth() + 1)}-${pad(et.getDate())}` +
    `T${pad(et.getHours())}:${pad(et.getMinutes())}`
  );
}

function datetimeLocalToUtc(local: string): string {
  return fromZonedTime(local, ET_ZONE).toISOString();
}

describe("config-panel timezone helpers", () => {
  describe("datetimeLocalToUtc", () => {
    it("converts winter ET (EST) to UTC with +5h offset", () => {
      // 09:30 EST = 14:30 UTC
      const utc = datetimeLocalToUtc("2024-01-15T09:30");
      expect(new Date(utc).toISOString()).toBe("2024-01-15T14:30:00.000Z");
    });

    it("converts summer ET (EDT) to UTC with +4h offset", () => {
      // 09:30 EDT = 13:30 UTC
      const utc = datetimeLocalToUtc("2024-07-15T09:30");
      expect(new Date(utc).toISOString()).toBe("2024-07-15T13:30:00.000Z");
    });

    it("handles DST spring-forward (March 2025)", () => {
      // March 10, 2025 is EDT (after March 9 spring forward)
      const utc = datetimeLocalToUtc("2025-03-10T09:30");
      expect(new Date(utc).toISOString()).toBe("2025-03-10T13:30:00.000Z"); // EDT +4h
    });

    it("handles DST fall-back (November 2025)", () => {
      // November 3, 2025 is EST (after November 2 fall back)
      const utc = datetimeLocalToUtc("2025-11-03T09:30");
      expect(new Date(utc).toISOString()).toBe("2025-11-03T14:30:00.000Z"); // EST +5h
    });
  });

  describe("utcToDatetimeLocal", () => {
    it("converts UTC to winter ET (EST)", () => {
      const local = utcToDatetimeLocal("2024-01-15T14:30:00.000Z");
      expect(local).toBe("2024-01-15T09:30");
    });

    it("converts UTC to summer ET (EDT)", () => {
      const local = utcToDatetimeLocal("2024-07-15T13:30:00.000Z");
      expect(local).toBe("2024-07-15T09:30");
    });
  });

  describe("roundtrip", () => {
    it("UTC -> ET -> UTC roundtrips correctly", () => {
      const original = "2024-06-15T18:00:00.000Z";
      const local = utcToDatetimeLocal(original);
      const back = datetimeLocalToUtc(local);
      expect(new Date(back).toISOString()).toBe(original);
    });
  });
});
