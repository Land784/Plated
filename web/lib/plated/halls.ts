import { HALL_SLUG, hallKeyOf, type HallKey, type HallSlug } from "./constants";

/** Step 1's answer: one hall, or both with one first. */
export type HallChoice = HallKey | "both";

/** The row's ordered slug list -> the step's answer. Unknown slugs are ignored. */
export function hallsFromRow(halls: unknown): { choice: HallChoice; first: HallKey } {
  const keys = (Array.isArray(halls) ? halls : [])
    .map((h) => (typeof h === "string" ? hallKeyOf(h) : null))
    .filter((k): k is HallKey => !!k);
  const unique = [...new Set(keys)];
  if (unique.length === 1) return { choice: unique[0], first: unique[0] };
  if (unique.length === 2) return { choice: "both", first: unique[0] };
  return { choice: "both", first: "N" };
}

/** Halls in the order the push renders them; the first is the preferred one. */
export function hallOrder(choice: HallChoice, first: HallKey): HallKey[] {
  if (choice !== "both") return [choice];
  return first === "N" ? ["N", "S"] : ["S", "N"];
}

export function hallsToRow(choice: HallChoice, first: HallKey): HallSlug[] {
  return hallOrder(choice, first).map((k) => HALL_SLUG[k]);
}
