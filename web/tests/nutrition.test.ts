import { describe, expect, it } from "vitest";

import { DEFAULT_PICKS, macrosToRow, nutritionErrors, nutritionFromRow } from "@/lib/plated/nutrition";

describe("nutrition settings", () => {
  it("reads a row saved before the planner rebuild as defaults with picks off", () => {
    const n = nutritionFromRow(null, { min_item_protein_g: 15, max_total_servings: 4 }, "10");
    expect(n.targets).toEqual({ protein: null, carbs: null, fat: null, calories: null });
    expect(n.picks).toEqual(DEFAULT_PICKS);
    expect(n.mainProteinG).toBe(10);
    expect(nutritionFromRow(null, null, "12.5").mainProteinG).toBe(12.5);
  });

  it("round-trips targets, writing only the ones that are set", () => {
    const n = nutritionFromRow({ protein: 60, calories: 700, fat: null }, { enabled: true }, 12);
    expect(n.picks.enabled).toBe(true);
    expect(n.mainProteinG).toBe(12);
    expect(macrosToRow(n.targets)).toEqual({ protein: 60, calories: 700 });
    expect(macrosToRow({ protein: null, carbs: null, fat: null, calories: null })).toBeNull();
  });

  it("flags out-of-range and cleared required fields", () => {
    const n = nutritionFromRow({ protein: 0 }, {}, 10);
    expect(nutritionErrors(n)).toEqual(["protein"]);
    expect(nutritionErrors({ ...n, targets: { ...n.targets, protein: 60 }, picks: { ...n.picks, tolerance_pct: NaN } })).toEqual([
      "tolerance_pct",
    ]);
  });
});
