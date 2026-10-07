import { describe, expect, it } from "vitest";

import { formFromRow, formToUpdate, needsSetup, parseSubscriberRow, stepValid } from "@/lib/plated/form";
import { hallOrder, hallsFromRow, hallsToRow } from "@/lib/plated/halls";
import {
  buildCatalog,
  deriveFavorites,
  deriveStations,
  normalizeStation,
  selectionFromRow,
  toggleFavorite,
  toggleStation,
  visibleStations,
  type StationViewRow,
} from "@/lib/plated/stations";

const N = "north-dining-hall";
const S = "south-dining-hall";

// Shaped like the `stations` view, deliberately out of order.
const VIEW: StationViewRow[] = [
  { station: "Pastaria", halls: [S], meals: ["lunch", "dinner"], is_food: true, example_dishes: ["Penne Pasta"] },
  { station: "Omelets", halls: [S], meals: ["breakfast"], is_food: true, example_dishes: [] },
  { station: "Mezze", halls: [S, N], meals: ["lunch", "dinner"], is_food: true, example_dishes: ["Pork Osso Buco"] },
  { station: "The Global Compass", halls: [N], meals: ["dinner"], is_food: true, example_dishes: ["Beef Pad See Ew"] },
  { station: "Global Compass", halls: [S], meals: ["lunch"], is_food: true, example_dishes: ["Pork Potsticker"] },
  { station: "Sunrise Kitchen", halls: [N], meals: ["breakfast"], is_food: true, example_dishes: null },
  { station: "Beverages", halls: [N, S], meals: ["lunch"], is_food: false, example_dishes: [] },
  { station: "Green & Grains", halls: [N], meals: ["lunch", "dinner"], is_food: true, example_dishes: ["Southwest Salad"] },
  { station: "Domer Diner", halls: [N, S], meals: ["breakfast", "lunch"], is_food: true, example_dishes: ["Smash Burger"] },
];

const catalog = buildCatalog(VIEW);
const ids = (names: string[]) => names.map(normalizeStation);

describe("catalog", () => {
  it("matches station names the way the push does", () => {
    expect(normalizeStation("  The   Global Compass ")).toBe("global compass");
    expect(normalizeStation("Crust & Co")).toBe("crust & co");
  });

  it("drops non-food stations, merges shared spellings and orders shared, North, South, breakfast", () => {
    expect(catalog.map((s) => s.name)).toEqual([
      "Domer Diner",
      "Global Compass",
      "Mezze",
      "Green & Grains",
      "Pastaria",
      "Sunrise Kitchen",
      "Omelets",
    ]);
    const compass = catalog.find((s) => s.id === "global compass")!;
    expect(compass.halls).toEqual(["N", "S"]);
    expect(compass.dishes).toEqual(["Beef Pad See Ew", "Pork Potsticker"]);
  });

  it("tags a station breakfast-only only when breakfast is its only meal", () => {
    const tagged = catalog.filter((s) => s.breakfastOnly).map((s) => s.name);
    expect(tagged).toEqual(["Sunrise Kitchen", "Omelets"]);
  });

  it("hides stations from a hall you didn't pick", () => {
    expect(visibleStations(catalog, ["N"]).map((s) => s.name)).toEqual([
      "Domer Diner",
      "Global Compass",
      "Mezze",
      "Green & Grains",
      "Sunrise Kitchen",
    ]);
  });
});

describe("stations written on save", () => {
  const allOn = selectionFromRow(catalog.map((s) => s.name), [], catalog);

  it("is every station in catalog order with no favorites", () => {
    expect(deriveStations(catalog, allOn)).toEqual(catalog.map((s) => s.name));
    expect(deriveFavorites(catalog, allOn)).toEqual([]);
  });

  it("puts favorites first in catalog order, not the order they were starred", () => {
    let sel = toggleFavorite(allOn, "pastaria");
    sel = toggleFavorite(sel, "mezze");
    expect(deriveStations(catalog, sel)).toEqual([
      "Mezze",
      "Pastaria",
      "Domer Diner",
      "Global Compass",
      "Green & Grains",
      "Sunrise Kitchen",
      "Omelets",
    ]);
    expect(deriveFavorites(catalog, sel)).toEqual(["Mezze", "Pastaria"]);
  });

  it("turning a favorite off un-stars it; starring an off station turns it on", () => {
    let sel = toggleFavorite(allOn, "mezze");
    sel = toggleStation(sel, "mezze");
    expect(sel.favorites).toEqual([]);
    expect(deriveStations(catalog, sel)).not.toContain("Mezze");
    sel = toggleStation(sel, "omelets");
    sel = toggleFavorite(sel, "omelets");
    expect(deriveStations(catalog, sel)[0]).toBe("Omelets");
  });

  it("reads a row's allowlist back: missing stations are off, names match loosely", () => {
    const sel = selectionFromRow(["the global compass", "Mezze", "Old Station"], ["Mezze"], catalog);
    expect(sel.favorites).toEqual(["mezze"]);
    expect(sel.off).toEqual(ids(["Domer Diner", "Green & Grains", "Pastaria", "Sunrise Kitchen", "Omelets"]));
    expect(sel.extra).toEqual(["Old Station"]);
    expect(deriveStations(catalog, sel)).toEqual(["Mezze", "Global Compass", "Old Station"]);
  });

  it("an empty allowlist is everything off, as the push treats it", () => {
    const sel = selectionFromRow([], [], catalog);
    expect(deriveStations(catalog, sel)).toEqual([]);
  });
});

describe("halls", () => {
  it("maps the ordered slug list to the step's answer and back", () => {
    expect(hallsFromRow([S, N])).toEqual({ choice: "both", first: "S" });
    expect(hallsFromRow([N])).toEqual({ choice: "N", first: "N" });
    expect(hallsFromRow([])).toEqual({ choice: "both", first: "N" });
    expect(hallsToRow("both", "S")).toEqual([S, N]);
    expect(hallsToRow("N", "S")).toEqual([N]);
    expect(hallOrder("S", "N")).toEqual(["S"]);
  });
});

describe("row <-> form", () => {
  const row = parseSubscriberRow({
    id: "abc",
    name: "Wes",
    halls: [N, S],
    stations: catalog.map((s) => s.name),
    favorites: [],
    schedule: { monday: { lunch: "12:00" } },
    active: true,
    ntfy_topic: "plated-xxxxxxxxxxxxxxxx",
    timezone: "America/New_York",
    created_at: "2026-10-07T12:00:00.123+00:00",
    updated_at: "2026-10-07T12:00:00.123Z",
  })!;

  it("round-trips without changes and never writes the topic", () => {
    const update = formToUpdate(formFromRow(row, catalog), catalog);
    expect(update).toEqual({
      name: "Wes",
      halls: [N, S],
      stations: catalog.map((s) => s.name),
      favorites: [],
      schedule: { monday: { lunch: "12:00" } },
      active: true,
    });
    expect(Object.keys(update)).not.toContain("ntfy_topic");
  });

  it("detects first run from untouched timestamps", () => {
    expect(needsSetup(row)).toBe(true);
    expect(needsSetup({ ...row, updated_at: "2026-10-07T12:05:00Z" })).toBe(false);
  });

  it("validates steps against the halls you picked", () => {
    let form = formFromRow(row, catalog);
    form = { ...form, hallChoice: "S", stations: { ...form.stations, off: ids(["Domer Diner", "Global Compass", "Mezze", "Pastaria", "Omelets"]) } };
    expect(stepValid(form, catalog, "what")).toBe(false);
    expect(stepValid({ ...form, hallChoice: "N" }, catalog, "what")).toBe(true);
  });
});
