// Shared vocabulary for the app. Slugs match the Python package (menu/users.py)
// and the Nutrislice menu types; labels are what people see.

export type HallKey = "N" | "S";
export type HallSlug = "north-dining-hall" | "south-dining-hall";

export const HALL_SLUG: Record<HallKey, HallSlug> = {
  N: "north-dining-hall",
  S: "south-dining-hall",
};

export const HALL_LABEL: Record<HallKey, string> = { N: "North", S: "South" };

export function hallKeyOf(slug: string): HallKey | null {
  if (slug === HALL_SLUG.N) return "N";
  if (slug === HALL_SLUG.S) return "S";
  return null;
}

export type Meal = "breakfast" | "brunch" | "lunch" | "dinner";

/** The meals the Preview page offers, in the mockup's order. */
export const MEALS: Meal[] = ["breakfast", "brunch", "lunch", "dinner"];

export const MEAL_LABEL: Record<Meal, string> = {
  breakfast: "Breakfast",
  brunch: "Brunch",
  lunch: "Lunch",
  dinner: "Dinner",
};

/** ntfy shows these tag names as emoji before the title. */
export const TAG_EMOJI: Record<string, string> = {
  fried_egg: "🍳",
  pancakes: "🥞",
  sandwich: "🥪",
  plate_with_cutlery: "🍽",
};

/** The tag the Python renderer gives each meal's push. */
export const MEAL_TAG: Record<Meal, string> = {
  breakfast: "fried_egg",
  brunch: "pancakes",
  lunch: "sandwich",
  dinner: "plate_with_cutlery",
};

export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** [key, short label, long label, the weekday name the database row uses] */
export const DAYS: [DayKey, string, string, string][] = [
  ["mon", "Mon", "Monday", "monday"],
  ["tue", "Tue", "Tuesday", "tuesday"],
  ["wed", "Wed", "Wednesday", "wednesday"],
  ["thu", "Thu", "Thursday", "thursday"],
  ["fri", "Fri", "Friday", "friday"],
  ["sat", "Sat", "Saturday", "saturday"],
  ["sun", "Sun", "Sunday", "sunday"],
];

export const DAY_KEYS: DayKey[] = DAYS.map((d) => d[0]);
export const WEEKDAY_KEYS: DayKey[] = ["mon", "tue", "wed", "thu", "fri"];

export const isWeekend = (d: DayKey): boolean => d === "sat" || d === "sun";

export function dayInfo(d: DayKey): [DayKey, string, string, string] {
  return DAYS.find((x) => x[0] === d)!;
}

/** The push body budget the Python renderer trims to (menu/digest.py). */
export const BYTE_BUDGET = 3000;
