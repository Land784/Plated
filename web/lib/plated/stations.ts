// The "What you like" step: the station catalog from the `stations` view,
// and the ordered list written to `subscribers.stations`.

import { hallKeyOf, type HallKey } from "./constants";

/** A row of the `public.stations` view (see the frontend spec's contracts). */
export type StationViewRow = {
  station: string;
  normalized?: string | null;
  halls?: string[] | null;
  meals?: string[] | null;
  last_seen?: string | null;
  is_food?: boolean | null;
  example_dishes?: string[] | null;
};

export type CatalogStation = {
  /** The normalized name; matching ignores case and a leading "The", as the push does. */
  id: string;
  /** The spelling shown and written to the row. */
  name: string;
  /** Halls it was seen at, North first. */
  halls: HallKey[];
  /** Seen only at breakfast and/or brunch. */
  breakfastOnly: boolean;
  /** Up to 3 recent mains, most frequent first. */
  dishes: string[];
};

/**
 * South's rotating bowl counter ("Athenian Rice Bowl", "Harvest Bowl", ...)
 * is one counter, so every bowl-named station is one group with this
 * normalized token, and the `stations` view labels it "Bowls".
 */
export const BOWLS_ID = "bowls";
export const BOWLS_LABEL = "Bowls";
const BOWL_WORD = /\bbowls?\b/;
/** Non-food names ("Harvest Bowl Toppings") are never grouped, as in the Python rule. */
const NOT_FOOD_WORD = /condiment|topping|dressing/;

/** Mirrors menu/digest.py normalize_station(), including the bowls group. */
export function normalizeStation(name: string): string {
  const id = name.replace(/\s+/g, " ").trim().toLowerCase().replace(/^the\s+/, "");
  return BOWL_WORD.test(id) && !NOT_FOOD_WORD.test(id) ? BOWLS_ID : id;
}

export function isBowlsGroup(station: Pick<CatalogStation, "id">): boolean {
  return station.id === BOWLS_ID;
}

/** A station seen only at these meals is a breakfast station (weekend brunch reuses them). */
const BREAKFAST_MEALS = new Set(["breakfast", "brunch"]);

const hasArticle = (name: string) => /^the\s+/i.test(name.trim());

/**
 * Turn view rows into the catalog: food stations only, shared spellings
 * merged ("The Global Compass" + "Global Compass"), in the fixed default
 * order the push uses for non-favorites:
 *   1. stations not breakfast-only, then breakfast-only ones;
 *   2. within those, stations at both halls, then North-only, then South-only;
 *   3. then by name.
 */
export function buildCatalog(rows: StationViewRow[]): CatalogStation[] {
  type Acc = { names: string[]; halls: Set<HallKey>; meals: Set<string>; dishes: string[] };
  const byId = new Map<string, Acc>();
  for (const row of rows) {
    if (!row || typeof row.station !== "string" || !row.station.trim()) continue;
    if (row.is_food === false) continue;
    const id = normalizeStation(row.station);
    const acc = byId.get(id) ?? { names: [], halls: new Set(), meals: new Set(), dishes: [] };
    acc.names.push(row.station.trim());
    for (const h of row.halls ?? []) {
      const key = hallKeyOf(h);
      if (key) acc.halls.add(key);
    }
    for (const m of row.meals ?? []) acc.meals.add(m);
    for (const d of row.example_dishes ?? []) {
      if (typeof d === "string" && d.trim() && !acc.dishes.includes(d.trim())) acc.dishes.push(d.trim());
    }
    byId.set(id, acc);
  }

  const catalog: CatalogStation[] = [];
  for (const [id, acc] of byId) {
    if (!acc.halls.size) continue; // seen only at a hall the app doesn't offer
    // The bowls group is written to the row as exactly "Bowls", whatever spellings fed it.
    const name = id === BOWLS_ID ? BOWLS_LABEL : (acc.names.find((n) => !hasArticle(n)) ?? acc.names[0]);
    const meals = [...acc.meals];
    catalog.push({
      id,
      name,
      halls: (["N", "S"] as HallKey[]).filter((h) => acc.halls.has(h)),
      breakfastOnly: meals.length > 0 && meals.every((m) => BREAKFAST_MEALS.has(m)),
      dishes: acc.dishes.slice(0, 3),
    });
  }

  const hallRank = (s: CatalogStation) => (s.halls.length === 2 ? 0 : s.halls[0] === "N" ? 1 : 2);
  return catalog.sort(
    (a, b) =>
      Number(a.breakfastOnly) - Number(b.breakfastOnly) ||
      hallRank(a) - hallRank(b) ||
      a.name.localeCompare(b.name, "en", { sensitivity: "base" }),
  );
}

export type StationSelection = {
  /** Catalog ids turned off. */
  off: string[];
  /** Catalog ids starred. */
  favorites: string[];
  /** Station names in the row that the catalog doesn't know (not seen in 14 days); kept, in order, after the rest. */
  extra: string[];
  /** Favorite names in the row that the catalog doesn't know; kept as they are. */
  extraFavorites: string[];
};

/**
 * Read the row's `stations` and `favorites` against the catalog. A catalog
 * station missing from the row is off (the row is an allowlist, and an
 * empty list sends nothing, as in the Python renderer).
 */
export function selectionFromRow(
  rowStations: string[],
  rowFavorites: string[],
  catalog: CatalogStation[],
): StationSelection {
  const ids = new Set(catalog.map((s) => s.id));
  const included = new Set(rowStations.map(normalizeStation));
  const favIds = new Set(rowFavorites.map(normalizeStation));
  const seen = new Set<string>();
  const extra = rowStations.filter((n) => {
    const id = normalizeStation(n);
    if (ids.has(id) || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  return {
    off: catalog.filter((s) => !included.has(s.id)).map((s) => s.id),
    // A starred station that is off is meaningless, so it is not a favorite.
    favorites: catalog.filter((s) => favIds.has(s.id) && included.has(s.id)).map((s) => s.id),
    extra,
    extraFavorites: rowFavorites.filter((n) => !ids.has(normalizeStation(n))),
  };
}

/**
 * The ordered list written to `subscribers.stations`: favorites (catalog
 * order), then every other included station (catalog order), then names
 * the catalog doesn't know. Stations at a hall you didn't pick keep their
 * state; the push only shows stations at halls it renders.
 */
export function deriveStations(catalog: CatalogStation[], sel: StationSelection): string[] {
  const on = catalog.filter((s) => !sel.off.includes(s.id));
  const fav = on.filter((s) => sel.favorites.includes(s.id));
  const rest = on.filter((s) => !sel.favorites.includes(s.id));
  return [...fav, ...rest].map((s) => s.name).concat(sel.extra);
}

/** The `favorites` column: starred names in catalog order. */
export function deriveFavorites(catalog: CatalogStation[], sel: StationSelection): string[] {
  return catalog
    .filter((s) => sel.favorites.includes(s.id) && !sel.off.includes(s.id))
    .map((s) => s.name)
    .concat(sel.extraFavorites);
}

/** Tap a card: turning a favorite off un-stars it. */
export function toggleStation(sel: StationSelection, id: string): StationSelection {
  if (!sel.off.includes(id)) {
    return { ...sel, off: [...sel.off, id], favorites: sel.favorites.filter((x) => x !== id) };
  }
  return { ...sel, off: sel.off.filter((x) => x !== id) };
}

/** Tap a star: starring an off station turns it on. */
export function toggleFavorite(sel: StationSelection, id: string): StationSelection {
  if (sel.favorites.includes(id)) return { ...sel, favorites: sel.favorites.filter((x) => x !== id) };
  return { ...sel, favorites: [...sel.favorites, id], off: sel.off.filter((x) => x !== id) };
}

/** Stations served at any of the chosen halls. */
export function visibleStations(catalog: CatalogStation[], halls: HallKey[]): CatalogStation[] {
  return catalog.filter((s) => s.halls.some((h) => halls.includes(h)));
}
