import type { DayKey } from "./constants";

const JS_DAY: DayKey[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

/** Parse "YYYY-MM-DD" as a calendar date (UTC midnight, so no zone shifts it). */
function utcDate(date: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = utcDate(value);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

export function dayKeyOf(date: string): DayKey {
  return JS_DAY[utcDate(date).getUTCDay()];
}

export function addDays(date: string, n: number): string {
  const d = utcDate(date);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** The Saturday that ends `date`'s Sunday-to-Saturday week (`date` itself on a Saturday). */
export function weekEndOf(date: string): string {
  return addDays(date, 6 - utcDate(date).getUTCDay());
}

/** Clamp an ISO date into [min, max] (string order is date order for YYYY-MM-DD). */
export function clampDate(date: string, min: string, max: string): string {
  return date < min ? min : date > max ? max : date;
}

/** "Thu Sep 24" */
export function fmtTitleDate(date: string): string {
  return utcDate(date)
    .toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })
    .replace(",", "");
}

/** "Thursday, September 24" */
export function fmtLongDate(date: string): string {
  return utcDate(date).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** "17:30" -> "5:30 PM" (or "5:30" without the suffix). */
export function fmt12(t: string, ampm = true): string {
  const [h, m] = t.split(":").map(Number);
  const h12 = ((h + 11) % 12) + 1;
  return `${h12}:${String(m).padStart(2, "0")}${ampm ? (h < 12 ? " AM" : " PM") : ""}`;
}

export function toMinutes(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

export type ZonedNow = { date: string; minutes: number };

/** The wall-clock date and minute of day in `timeZone` (the subscriber's, not the browser's). */
export function zonedNow(timeZone: string, at: Date = new Date()): ZonedNow {
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(at);
  } catch {
    return zonedNow("America/New_York", at);
  }
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "0";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    minutes: (Number(get("hour")) % 24) * 60 + Number(get("minute")),
  };
}

/** "Eastern" for the default zone; otherwise the zone name. */
export function zoneLabel(timeZone: string): string {
  return timeZone === "America/New_York" ? "Eastern" : timeZone;
}
