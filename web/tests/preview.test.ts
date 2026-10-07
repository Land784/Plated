import { describe, expect, it } from "vitest";

import { cleanName, formFromRow, parseSubscriberRow } from "@/lib/plated/form";
import {
  NO_MENU_REASON,
  buildPreviewRequest,
  defaultPreviewChoice,
  displayTitle,
  friendlyReason,
  ntfyPublishUrl,
  parsePreviewResponse,
  previewDateRange,
  servedReason,
  utf8Bytes,
} from "@/lib/plated/preview";
import { buildCatalog, toggleFavorite, toggleStation } from "@/lib/plated/stations";
import { clampDate } from "@/lib/plated/time";

const N = "north-dining-hall";
const S = "south-dining-hall";

const catalog = buildCatalog([
  { station: "Domer Diner", halls: [N, S], meals: ["lunch", "dinner"], is_food: true },
  { station: "La Mesa", halls: [N, S], meals: ["lunch", "dinner"], is_food: true },
  { station: "Pastaria", halls: [S], meals: ["dinner"], is_food: true },
]);

const row = parseSubscriberRow({
  id: "abc",
  name: "Wes",
  halls: [N, S],
  stations: ["Domer Diner", "La Mesa", "Pastaria"],
  favorites: [],
  schedule: {
    monday: { lunch: "12:00", dinner: "17:30" },
    saturday: { brunch: "11:00", dinner: "17:30" },
  },
  active: true,
  ntfy_topic: "plated-xxxxxxxxxxxxxxxx",
  timezone: "America/New_York",
  created_at: null,
  updated_at: null,
})!;

describe("preview request", () => {
  it("has exactly the contract's keys, from the unsaved form", () => {
    let form = formFromRow(row, catalog);
    form = { ...form, first: "S", stations: toggleFavorite(toggleStation(form.stations, "la mesa"), "pastaria") };
    const req = buildPreviewRequest(form, catalog, "dinner", "2026-10-07");
    expect(req).toEqual({
      halls: [S, N],
      stations: ["Pastaria", "Domer Diner"],
      meal: "dinner",
      date: "2026-10-07",
    });
    expect(Object.keys(req).sort()).toEqual(["date", "halls", "meal", "stations"]);
    expect(JSON.parse(JSON.stringify(req))).toEqual(req);
  });

  it("sends one hall when one is picked", () => {
    const form = { ...formFromRow(row, catalog), hallChoice: "N" as const };
    expect(buildPreviewRequest(form, catalog, "lunch", "2026-10-05").halls).toEqual([N]);
  });

  it("defaults to the next scheduled meal in the subscriber's time", () => {
    const form = formFromRow(row, catalog);
    // Monday 2026-10-05 at 13:00: lunch has passed, dinner is next.
    expect(defaultPreviewChoice(form, { date: "2026-10-05", minutes: 13 * 60 })).toEqual({
      meal: "dinner",
      date: "2026-10-05",
    });
    // Tuesday: nothing until Saturday brunch.
    expect(defaultPreviewChoice(form, { date: "2026-10-06", minutes: 0 })).toEqual({
      meal: "brunch",
      date: "2026-10-10",
    });
  });
});

describe("preview response", () => {
  it("accepts a rendered push", () => {
    const body = "North: Smash Burger\n\nData may be incomplete; confirm allergens with staff.";
    const res = parsePreviewResponse({ title: "Dinner · Wed Oct 7", tags: ["plate_with_cutlery"], body, bytes: 1244, sent: true });
    expect(res).toEqual({ sent: true, title: "Dinner · Wed Oct 7", tags: ["plate_with_cutlery"], body, bytes: 1244 });
    expect(displayTitle("Dinner · Wed Oct 7", ["plate_with_cutlery"])).toBe("🍽 Dinner · Wed Oct 7");
  });

  it("counts bytes itself when the reply has none", () => {
    const res = parsePreviewResponse({ title: "t", tags: [], body: "Crust & Co ──", sent: true });
    expect(res).toMatchObject({ sent: true, bytes: utf8Bytes("Crust & Co ──") });
    expect(utf8Bytes("──")).toBe(6);
  });

  it("passes through sent:false with its reason", () => {
    expect(parsePreviewResponse({ sent: false, reason: "no menu published" })).toEqual({
      sent: false,
      reason: "no menu published",
    });
    expect(parsePreviewResponse({ sent: true })).toMatchObject({ sent: false });
    expect(parsePreviewResponse(null)).toMatchObject({ sent: false });
  });

  it("knows which meals aren't served on a day", () => {
    expect(servedReason("brunch", "2026-10-07")).toMatch(/No brunch on Wednesdays/);
    expect(servedReason("lunch", "2026-10-10")).toMatch(/Weekends serve brunch/);
    expect(servedReason("dinner", "2026-10-10")).toBeNull();
  });
});

describe("ntfy test push", () => {
  it("puts title and tags in the query string", () => {
    expect(ntfyPublishUrl("plated-abc", "Dinner · Wed Oct 7", ["plate_with_cutlery"])).toBe(
      "https://ntfy.sh/plated-abc?title=Dinner%20%C2%B7%20Wed%20Oct%207&tags=plate_with_cutlery",
    );
  });
});

describe("stored week", () => {
  it("offers today through the coming Saturday", () => {
    expect(previewDateRange({ date: "2026-10-07", minutes: 0 })).toEqual({ min: "2026-10-07", max: "2026-10-10" });
    expect(previewDateRange({ date: "2026-10-10", minutes: 0 })).toEqual({ min: "2026-10-10", max: "2026-10-10" });
    expect(previewDateRange({ date: "2026-10-11", minutes: 0 })).toEqual({ min: "2026-10-11", max: "2026-10-17" });
    expect(clampDate("2026-10-20", "2026-10-07", "2026-10-10")).toBe("2026-10-10");
    expect(clampDate("2026-10-01", "2026-10-07", "2026-10-10")).toBe("2026-10-07");
  });

  it("falls back to today's dinner when the next text is past Saturday", () => {
    const form = formFromRow(row, catalog);
    // Saturday 2026-10-10 at 20:00: the next text is Monday lunch, outside the stored week.
    expect(defaultPreviewChoice(form, { date: "2026-10-10", minutes: 20 * 60 })).toEqual({
      meal: "dinner",
      date: "2026-10-10",
    });
  });

  it("explains a day with nothing stored", () => {
    expect(friendlyReason(NO_MENU_REASON)).toBe("Nothing stored yet for that day; menus appear the morning of.");
    expect(friendlyReason("something else")).toBe("something else");
  });
});

describe("names", () => {
  it("trims and caps at 60 characters", () => {
    expect(cleanName("  Wes  ")).toBe("Wes");
    expect(cleanName("x".repeat(70))).toHaveLength(60);
  });
});
