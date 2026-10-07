// The "When" step: four meal chips plus a seven-day editor, mapped to and
// from the `subscribers.schedule` column ({weekday: {meal: "HH:MM"}}).
//
// The form always holds all seven days. Each chip writes through to every
// day it covers; the day editor then overrides single days. A chip is on
// if any of its days is on, and shows the most common time.

import {
  DAYS,
  DAY_KEYS,
  MEAL_LABEL,
  WEEKDAY_KEYS,
  dayInfo,
  isWeekend,
  type DayKey,
  type Meal,
} from "./constants";
import { addDays, dayKeyOf, fmt12, toMinutes, type ZonedNow } from "./time";

export type MealSlot = { on: boolean; t: string };
export type DaySchedule = Partial<Record<Meal, MealSlot>>;
export type Days = Record<DayKey, DaySchedule>;

/** The row's shape: lower-case weekday -> meal slug -> "HH:MM". */
export type RowSchedule = Record<string, Record<string, string>>;

export const WEEKDAY_MEALS: Meal[] = ["breakfast", "lunch", "dinner"];
export const WEEKEND_MEALS: Meal[] = ["brunch", "dinner"];

export const DEFAULT_TIME: Record<Meal, string> = {
  breakfast: "08:00",
  brunch: "11:00",
  lunch: "12:00",
  dinner: "17:30",
};

export type Chip = { meal: Meal; label: string; when: string; days: DayKey[] };

export const CHIPS: Chip[] = [
  { meal: "breakfast", label: "Breakfast", when: "Mon–Fri", days: WEEKDAY_KEYS },
  { meal: "lunch", label: "Lunch", when: "Mon–Fri", days: WEEKDAY_KEYS },
  { meal: "dinner", label: "Dinner", when: "Every day", days: DAY_KEYS },
  { meal: "brunch", label: "Weekend brunch", when: "Sat & Sun", days: ["sat", "sun"] },
];

export function mealsFor(day: DayKey): Meal[] {
  return isWeekend(day) ? WEEKEND_MEALS : WEEKDAY_MEALS;
}

/** First-run defaults: lunch 12:00 and dinner 17:30 weekdays, brunch 11:00 and dinner 17:30 weekends. */
export function defaultDays(): Days {
  const days = {} as Days;
  for (const d of DAY_KEYS) {
    days[d] = isWeekend(d)
      ? { brunch: { on: true, t: "11:00" }, dinner: { on: true, t: "17:30" } }
      : {
          breakfast: { on: false, t: "08:00" },
          lunch: { on: true, t: "12:00" },
          dinner: { on: true, t: "17:30" },
        };
  }
  return days;
}

/** "9:5" or "09:05:00" -> "09:05"; anything else -> null. */
export function normalizeTime(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const m = /^\s*(\d{1,2}):(\d{1,2})(?::\d{1,2})?\s*$/.exec(raw);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
}

function mostCommon(times: string[]): string | null {
  if (!times.length) return null;
  const counts = new Map<string, number>();
  for (const t of times) counts.set(t, (counts.get(t) ?? 0) + 1);
  return times.reduce((a, b) => ((counts.get(b) ?? 0) > (counts.get(a) ?? 0) ? b : a), times[0]);
}

/**
 * Read the row's schedule into seven editable days. Entries the editor
 * can't show (late-lunch, lunch on a Saturday, an unparseable time) are
 * returned in `extra` and written back unchanged on save.
 */
export function scheduleFromRow(raw: unknown): { days: Days; extra: RowSchedule } {
  const row: Record<string, Record<string, unknown>> = {};
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    for (const [day, meals] of Object.entries(raw as Record<string, unknown>)) {
      if (!meals || typeof meals !== "object" || Array.isArray(meals)) continue;
      const key = day.trim().toLowerCase();
      row[key] = { ...(row[key] ?? {}) };
      for (const [meal, t] of Object.entries(meals as Record<string, unknown>)) {
        row[key][meal.trim().toLowerCase()] = t;
      }
    }
  }

  const extra: RowSchedule = {};
  const addExtra = (day: string, meal: string, value: unknown) => {
    if (typeof value !== "string") return;
    extra[day] = { ...(extra[day] ?? {}), [meal]: value };
  };

  const known = new Set(DAYS.map((d) => d[3]));
  for (const [day, meals] of Object.entries(row)) {
    if (!known.has(day)) for (const [meal, t] of Object.entries(meals)) addExtra(day, meal, t);
  }

  // A meal that is off on a day gets that meal's usual time, so turning it on lands somewhere sensible.
  const usual = {} as Record<Meal, string>;
  for (const meal of Object.keys(DEFAULT_TIME) as Meal[]) {
    const seen = DAYS.map((d) => normalizeTime(row[d[3]]?.[meal])).filter((t): t is string => !!t);
    usual[meal] = mostCommon(seen) ?? DEFAULT_TIME[meal];
  }

  const days = {} as Days;
  for (const [key, , , rowName] of DAYS) {
    const meals = row[rowName] ?? {};
    const editable = mealsFor(key);
    const day: DaySchedule = {};
    for (const meal of editable) {
      const t = normalizeTime(meals[meal]);
      day[meal] = t ? { on: true, t } : { on: false, t: usual[meal] };
    }
    for (const [meal, value] of Object.entries(meals)) {
      const isEditable = (editable as string[]).includes(meal);
      if (!isEditable || !normalizeTime(value)) addExtra(rowName, meal, value);
    }
    days[key] = day;
  }
  return { days, extra };
}

/** Write the seven days back as the row's schedule, merging `extra` in. */
export function scheduleToRow(days: Days, extra: RowSchedule = {}): RowSchedule {
  const out: RowSchedule = {};
  for (const [key, , , rowName] of DAYS) {
    const meals: Record<string, string> = {};
    for (const meal of mealsFor(key)) {
      const slot = days[key][meal];
      if (slot?.on) meals[meal] = slot.t;
    }
    for (const [meal, t] of Object.entries(extra[rowName] ?? {})) {
      if (!(meal in meals)) meals[meal] = t;
    }
    if (Object.keys(meals).length) out[rowName] = meals;
  }
  for (const [day, meals] of Object.entries(extra)) {
    if (!(day in out) && !DAYS.some((d) => d[3] === day) && Object.keys(meals).length) out[day] = { ...meals };
  }
  return out;
}

export type ChipState = { on: boolean; t: string; varies: boolean; odd: DayKey[] };

/** One chip across the days it covers: on if any day has it; the time shown is the most common one. */
export function chipState(days: Days, chip: Chip): ChipState {
  const slot = (d: DayKey) => days[d][chip.meal] ?? { on: false, t: DEFAULT_TIME[chip.meal] };
  const onDays = chip.days.filter((d) => slot(d).on);
  const pool = (onDays.length ? onDays : chip.days).map((d) => slot(d).t);
  const t = mostCommon(pool) ?? DEFAULT_TIME[chip.meal];
  const on = onDays.length > 0;
  const odd = chip.days.filter((d) => slot(d).on !== on || (on && slot(d).t !== t));
  return { on, t, varies: on && onDays.some((d) => slot(d).t !== t), odd };
}

function mapDays(days: Days, fn: (day: DayKey, sched: DaySchedule) => DaySchedule): Days {
  const out = {} as Days;
  for (const d of DAY_KEYS) out[d] = fn(d, days[d]);
  return out;
}

/** Tapping a chip turns its meal on (or off) on every day it covers. */
export function toggleChip(days: Days, meal: Meal): Days {
  const chip = CHIPS.find((c) => c.meal === meal)!;
  const on = !chipState(days, chip).on;
  return mapDays(days, (d, s) =>
    chip.days.includes(d) && s[meal] ? { ...s, [meal]: { ...s[meal]!, on } } : s,
  );
}

/** Typing in a chip's time box sets that meal's time on all its days (resetting one-off days). */
export function setChipTime(days: Days, meal: Meal, t: string): Days {
  const chip = CHIPS.find((c) => c.meal === meal)!;
  return mapDays(days, (d, s) =>
    chip.days.includes(d) && s[meal] ? { ...s, [meal]: { ...s[meal]!, t } } : s,
  );
}

export function setSlot(days: Days, day: DayKey, meal: Meal, patch: Partial<MealSlot>): Days {
  return mapDays(days, (d, s) => (d === day && s[meal] ? { ...s, [meal]: { ...s[meal]!, ...patch } } : s));
}

export function anyMealOn(days: Days): boolean {
  return CHIPS.some((c) => chipState(days, c).on);
}

export function breakfastScheduled(days: Days): boolean {
  return DAY_KEYS.some((d) => days[d].breakfast?.on);
}

/** Short labels of days that differ from their chips, in week order ("Tue", "Sat"). */
export function oddDays(days: Days): string[] {
  const odd = new Set(CHIPS.flatMap((c) => chipState(days, c).odd));
  return DAYS.filter(([d]) => odd.has(d)).map((d) => d[1]);
}

export function daySummary(days: Days, day: DayKey): string {
  const on = mealsFor(day)
    .filter((m) => days[day][m]?.on)
    .map((m) => `${MEAL_LABEL[m]} ${fmt12(days[day][m]!.t)}`);
  return on.length ? on.join(" · ") : "No texts";
}

export type NextText = { meal: Meal; date: string; t: string; inDays: number };

/** The next scheduled text after `now` (the subscriber's local date and minute), within a week. */
export function nextScheduled(days: Days, now: ZonedNow): NextText | null {
  for (let i = 0; i < 8; i++) {
    const date = addDays(now.date, i);
    const due = (Object.entries(days[dayKeyOf(date)]) as [Meal, MealSlot][])
      .filter(([, v]) => v.on)
      .sort((a, b) => a[1].t.localeCompare(b[1].t));
    for (const [meal, v] of due) {
      if (i > 0 || toMinutes(v.t) > now.minutes) return { meal, date, t: v.t, inDays: i };
    }
  }
  return null;
}

/** "lunch today, 12:00 PM" */
export function nextTextLabel(next: NextText): string {
  const when =
    next.inDays === 0 ? "today" : next.inDays === 1 ? "tomorrow" : "on " + dayInfo(dayKeyOf(next.date))[2];
  return `${MEAL_LABEL[next.meal].toLowerCase()} ${when}, ${fmt12(next.t)}`;
}
