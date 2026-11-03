// Nutrition settings: per-meal targets and how picked plates are built.
// Mirrors menu/users.py (parse_user is the real validator; the database
// checks in supabase/migrations/20261102000000_nutrition.sql guard writes).

export const NUTRIENTS = ["protein", "carbs", "fat", "calories"] as const;
export type Nutrient = (typeof NUTRIENTS)[number];

export const NUTRIENT_LABEL: Record<Nutrient, string> = {
  protein: "Protein (g)",
  carbs: "Carbs (g)",
  fat: "Fat (g)",
  calories: "Calories",
};

/** Nutrislice's allergen tags, as spelled in stored menus. */
export const ALLERGENS = [
  "Dairy",
  "Egg",
  "Fish",
  "Shellfish",
  "Wheat",
  "Soy",
  "Sesame",
  "Pork",
  "Peanuts",
  "Tree Nuts",
] as const;

export type Picks = {
  enabled: boolean;
  tolerance_pct: number;
  side_min_calories: number;
  max_main_servings: number;
  max_item_calories: number;
  exclude_allergens: string[];
  unknown_allergens: "flag" | "exclude";
};

export type Nutrition = {
  targets: Record<Nutrient, number | null>;
  picks: Picks;
  mainProteinG: number;
};

export const DEFAULT_PICKS: Picks = {
  enabled: false,
  tolerance_pct: 15,
  side_min_calories: 50,
  max_main_servings: 2,
  max_item_calories: 1200,
  exclude_allergens: [],
  unknown_allergens: "flag",
};

/** Each editable number's allowed range (matches the database checks). */
export const LIMITS = {
  target: [1, 10000],
  tolerance_pct: [1, 100],
  side_min_calories: [0, 5000],
  max_item_calories: [1, 20000],
  mainProteinG: [0, 200],
} as const;

// PostgREST can send a numeric column as a string; read it rather than fall back to a default.
const num = (v: unknown): number | null => {
  const n = typeof v === "string" && v.trim() ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};

export function nutritionFromRow(macros: unknown, picks: unknown, mainProteinG: unknown): Nutrition {
  const m = (macros && typeof macros === "object" ? macros : {}) as Record<string, unknown>;
  const p = (picks && typeof picks === "object" ? picks : {}) as Record<string, unknown>;
  const targets = Object.fromEntries(NUTRIENTS.map((n) => [n, num(m[n])])) as Record<Nutrient, number | null>;
  return {
    targets,
    picks: {
      enabled: p.enabled === true,
      tolerance_pct: num(p.tolerance_pct) ?? DEFAULT_PICKS.tolerance_pct,
      side_min_calories: num(p.side_min_calories) ?? DEFAULT_PICKS.side_min_calories,
      max_main_servings: num(p.max_main_servings) ?? DEFAULT_PICKS.max_main_servings,
      max_item_calories: num(p.max_item_calories) ?? DEFAULT_PICKS.max_item_calories,
      exclude_allergens: Array.isArray(p.exclude_allergens)
        ? p.exclude_allergens.filter((a): a is string => typeof a === "string")
        : [],
      unknown_allergens: p.unknown_allergens === "exclude" ? "exclude" : "flag",
    },
    mainProteinG: num(mainProteinG) ?? 10,
  };
}

/** The row's macros: only the targets that are set, or null for none. */
export function macrosToRow(targets: Nutrition["targets"]): Partial<Record<Nutrient, number>> | null {
  const set = NUTRIENTS.filter((n) => targets[n] !== null).map((n) => [n, targets[n]] as const);
  return set.length ? Object.fromEntries(set) : null;
}

const inRange = (v: number | null, [lo, hi]: readonly [number, number]) => v !== null && v >= lo && v <= hi;

/** Field ids with an out-of-range value; empty when the form can be saved. */
export function nutritionErrors(n: Nutrition): string[] {
  const errors: string[] = NUTRIENTS.filter((k) => n.targets[k] !== null && !inRange(n.targets[k], LIMITS.target));
  for (const k of ["tolerance_pct", "side_min_calories", "max_item_calories"] as const)
    if (!inRange(n.picks[k], LIMITS[k])) errors.push(k);
  if (!inRange(n.mainProteinG, LIMITS.mainProteinG)) errors.push("mainProteinG");
  return errors;
}
