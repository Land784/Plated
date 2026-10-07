import { describe, expect, it } from "vitest";

import {
  CHIPS,
  chipState,
  daySummary,
  defaultDays,
  nextScheduled,
  nextTextLabel,
  normalizeTime,
  oddDays,
  scheduleFromRow,
  scheduleToRow,
  setChipTime,
  setSlot,
  toggleChip,
} from "@/lib/plated/schedule";

const chip = (meal: string) => CHIPS.find((c) => c.meal === meal)!;

// The schedule the backend's invite writes for a new subscriber.
const DEFAULT_ROW = {
  monday: { lunch: "12:00", dinner: "17:30" },
  tuesday: { lunch: "12:00", dinner: "17:30" },
  wednesday: { lunch: "12:00", dinner: "17:30" },
  thursday: { lunch: "12:00", dinner: "17:30" },
  friday: { lunch: "12:00", dinner: "17:30" },
  saturday: { brunch: "11:00", dinner: "17:30" },
  sunday: { brunch: "11:00", dinner: "17:30" },
};

describe("schedule row <-> days", () => {
  it("reads the default row as the default chips", () => {
    const { days, extra } = scheduleFromRow(DEFAULT_ROW);
    expect(days).toEqual(defaultDays());
    expect(extra).toEqual({});
    expect(CHIPS.map((c) => chipState(days, c).on)).toEqual([false, true, true, true]);
  });

  it("writes the default days back as the default row", () => {
    expect(scheduleToRow(defaultDays())).toEqual(DEFAULT_ROW);
  });

  it("round-trips a row with per-day times", () => {
    const row = {
      monday: { lunch: "11:15", dinner: "17:30" },
      tuesday: { lunch: "12:45", dinner: "17:30" },
      friday: { lunch: "11:15", dinner: "17:00" },
      saturday: { brunch: "10:30", dinner: "17:00" },
    };
    const { days, extra } = scheduleFromRow(row);
    expect(scheduleToRow(days, extra)).toEqual(row);
  });

  it("keeps entries the editor can't show and writes them back", () => {
    const row = {
      monday: { lunch: "12:00", "late-lunch": "14:00" },
      saturday: { lunch: "12:00", dinner: "17:30" },
    };
    const { days, extra } = scheduleFromRow(row);
    expect(extra).toEqual({ monday: { "late-lunch": "14:00" }, saturday: { lunch: "12:00" } });
    expect(days.sat.dinner).toEqual({ on: true, t: "17:30" });
    expect(scheduleToRow(days, extra)).toEqual(row);
  });

  it("normalizes case and unpadded times", () => {
    const { days } = scheduleFromRow({ Monday: { Lunch: "9:05" } });
    expect(days.mon.lunch).toEqual({ on: true, t: "09:05" });
  });

  it("gives an off day the meal's usual time", () => {
    const { days } = scheduleFromRow({ monday: { lunch: "11:15" }, tuesday: { lunch: "11:15" } });
    expect(days.wed.lunch).toEqual({ on: false, t: "11:15" });
    expect(days.wed.dinner).toEqual({ on: false, t: "17:30" });
  });

  it("treats a missing or malformed schedule as nothing scheduled", () => {
    for (const raw of [undefined, null, {}, [], "x"]) {
      const { days } = scheduleFromRow(raw);
      expect(scheduleToRow(days)).toEqual({});
    }
  });

  it("validates times", () => {
    expect(normalizeTime("17:30")).toBe("17:30");
    expect(normalizeTime("17:30:00")).toBe("17:30");
    expect(normalizeTime("24:00")).toBeNull();
    expect(normalizeTime("noon")).toBeNull();
    expect(normalizeTime(1730)).toBeNull();
  });
});

describe("chips", () => {
  it("toggling a chip writes through to every day it covers", () => {
    const days = toggleChip(defaultDays(), "breakfast");
    expect(scheduleToRow(days).monday).toEqual({ breakfast: "08:00", lunch: "12:00", dinner: "17:30" });
    expect(scheduleToRow(days).saturday).toEqual({ brunch: "11:00", dinner: "17:30" });
    expect(scheduleToRow(toggleChip(days, "breakfast"))).toEqual(DEFAULT_ROW);
  });

  it("dinner covers all seven days", () => {
    const row = scheduleToRow(toggleChip(defaultDays(), "dinner"));
    expect(Object.values(row).every((m) => !("dinner" in m))).toBe(true);
  });

  it("a chip is on if any of its days is on, and turning it on turns them all on", () => {
    let days = defaultDays();
    for (const d of ["mon", "tue", "wed", "thu"] as const) days = setSlot(days, d, "lunch", { on: false });
    expect(chipState(days, chip("lunch"))).toMatchObject({ on: true, odd: ["mon", "tue", "wed", "thu"] });
    days = toggleChip(days, "lunch"); // on -> off everywhere
    expect(chipState(days, chip("lunch")).on).toBe(false);
    days = toggleChip(days, "lunch");
    expect(chipState(days, chip("lunch"))).toMatchObject({ on: true, varies: false, odd: [] });
  });

  it("shows the most common time and flags the days that differ", () => {
    const days = setSlot(defaultDays(), "tue", "lunch", { t: "12:45" });
    expect(chipState(days, chip("lunch"))).toEqual({ on: true, t: "12:00", varies: true, odd: ["tue"] });
    expect(oddDays(days)).toEqual(["Tue"]);
    expect(daySummary(days, "tue")).toBe("Lunch 12:45 PM · Dinner 5:30 PM");
  });

  it("typing a chip time resets one-off days", () => {
    let days = setSlot(defaultDays(), "tue", "lunch", { t: "12:45" });
    days = setChipTime(days, "lunch", "11:30");
    expect(chipState(days, chip("lunch"))).toEqual({ on: true, t: "11:30", varies: false, odd: [] });
    expect(scheduleToRow(days).saturday).toEqual({ brunch: "11:00", dinner: "17:30" });
  });

  it("a day with a meal skipped is odd", () => {
    const days = setSlot(defaultDays(), "sun", "dinner", { on: false });
    expect(oddDays(days)).toEqual(["Sun"]);
    expect(scheduleToRow(days).sunday).toEqual({ brunch: "11:00" });
  });
});

describe("next scheduled text", () => {
  // 2026-10-07 is a Wednesday.
  it("finds the next meal later today", () => {
    const next = nextScheduled(defaultDays(), { date: "2026-10-07", minutes: 9 * 60 });
    expect(next).toEqual({ meal: "lunch", date: "2026-10-07", t: "12:00", inDays: 0 });
    expect(nextTextLabel(next!)).toBe("lunch today, 12:00 PM");
  });

  it("rolls over to tomorrow after the last meal", () => {
    const next = nextScheduled(defaultDays(), { date: "2026-10-09", minutes: 20 * 60 }); // Friday night
    expect(next).toEqual({ meal: "brunch", date: "2026-10-10", t: "11:00", inDays: 1 });
    expect(nextTextLabel(next!)).toBe("brunch tomorrow, 11:00 AM");
  });

  it("returns null when nothing is scheduled", () => {
    const { days } = scheduleFromRow({});
    expect(nextScheduled(days, { date: "2026-10-07", minutes: 0 })).toBeNull();
  });
});
