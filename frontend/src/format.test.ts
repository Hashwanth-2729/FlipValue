import { afterEach, describe, expect, it, vi } from "vitest";

import { count, day, daysSince, money, month } from "./format";
import { addHistory, readHistory, removeHistory } from "./history";

describe("money", () => {
  it("formats INR with Indian digit grouping and USD with US grouping", () => {
    expect(money(2200000, "INR")).toBe("₹22,00,000");
    expect(money(180, "USD")).toBe("$180");
    expect(money(180.5, "USD")).toBe("$180.50");
  });

  it("keeps a missing value distinct from zero", () => {
    expect(money(null, "INR")).toBe("—");
    expect(money(undefined, "USD")).toBe("—");
    expect(money(0, "INR")).toBe("₹0");
  });
});

describe("dates", () => {
  it("formats ISO dates without timezone drift", () => {
    expect(day("2026-10-01")).toBe("1 Oct 2026");
    expect(day("2026-10-21T23:30:00Z")).toBe("21 Oct 2026");
    expect(day(null)).toBe("—");
    expect(month("2026-03")).toBe("Mar 2026");
    expect(daysSince("2026-10-01", new Date("2026-10-21T12:00:00Z"))).toBe(20);
  });

  it("pluralises counts", () => {
    expect(count(1, "sale")).toBe("1 sale");
    expect(count(1200, "sale")).toBe("1,200 sales");
  });
});

describe("history", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("adds, de-duplicates and removes entries", () => {
    addHistory({ id: "a", deleteToken: "t", label: "A", savedAt: "2026-10-01" });
    addHistory({ id: "b", deleteToken: "t", label: "B", savedAt: "2026-10-02" });
    addHistory({ id: "a", deleteToken: "t", label: "A2", savedAt: "2026-10-03" });
    expect(readHistory().map((e) => e.label)).toEqual(["A2", "B"]);
    removeHistory("a");
    expect(readHistory().map((e) => e.id)).toEqual(["b"]);
  });

  it("survives blocked or corrupt storage", () => {
    window.localStorage.setItem("flipvalue.saved.v1", "{not json");
    expect(readHistory()).toEqual([]);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(addHistory({ id: "x", deleteToken: "t", label: "X", savedAt: "" })).toBe(false);
  });
});
