// The Preview page's request to the Python preview function
// (web/api/preview.py, owned by the backend) and the test push to ntfy.

import {
  MEALS,
  MEAL_LABEL,
  MEAL_TAG,
  TAG_EMOJI,
  dayInfo,
  isWeekend,
  type HallSlug,
  type Meal,
} from "./constants";
import { formToUpdate, type FormState } from "./form";
import { nextScheduled } from "./schedule";
import type { CatalogStation } from "./stations";
import { dayKeyOf, fmtTitleDate, isIsoDate, type ZonedNow } from "./time";

export const PREVIEW_ENDPOINT = "/api/preview";

/** `POST /api/preview` body, per the frontend spec's contract. */
export type PreviewRequest = {
  halls: HallSlug[];
  stations: string[];
  meal: Meal;
  date: string;
};

export type PreviewResult =
  | { sent: true; title: string; tags: string[]; body: string; bytes: number }
  | { sent: false; reason: string };

/** The current (possibly unsaved) form, rendered the way the saved row would be. */
export function buildPreviewRequest(
  form: FormState,
  catalog: CatalogStation[],
  meal: Meal,
  date: string,
): PreviewRequest {
  const update = formToUpdate(form, catalog);
  return { halls: update.halls, stations: update.stations, meal, date };
}

export function utf8Bytes(s: string): number {
  return new TextEncoder().encode(s).length;
}

/** Validate the function's JSON. Anything unexpected becomes a `sent: false` with a reason. */
export function parsePreviewResponse(raw: unknown): PreviewResult {
  if (!raw || typeof raw !== "object") return { sent: false, reason: "The preview service sent an unexpected reply." };
  const r = raw as Record<string, unknown>;
  if (r.sent === false) {
    return { sent: false, reason: typeof r.reason === "string" && r.reason ? r.reason : "Nothing would be sent." };
  }
  if (typeof r.title !== "string" || typeof r.body !== "string") {
    return { sent: false, reason: "The preview service sent an unexpected reply." };
  }
  const tags = Array.isArray(r.tags) ? r.tags.filter((t): t is string => typeof t === "string") : [];
  const bytes = typeof r.bytes === "number" && Number.isFinite(r.bytes) ? r.bytes : utf8Bytes(r.body);
  return { sent: true, title: r.title, tags, body: r.body, bytes };
}

/** "🍽 Dinner · Thu Sep 24": ntfy puts the tag's emoji before the title. */
export function displayTitle(title: string, tags: string[]): string {
  const emoji = tags.map((t) => TAG_EMOJI[t]).find(Boolean);
  return emoji ? `${emoji} ${title}` : title;
}

/** The title a push for this meal and date would have, for when there is no push to show. */
export function fallbackTitle(meal: Meal, date: string): string {
  if (!isIsoDate(date)) return MEAL_LABEL[meal];
  return displayTitle(`${MEAL_LABEL[meal]} · ${fmtTitleDate(date)}`, [MEAL_TAG[meal]]);
}

/** Meals a hall never serves on that day; no need to ask the server. */
export function servedReason(meal: Meal, date: string): string | null {
  const day = dayKeyOf(date);
  if (meal === "brunch" && !isWeekend(day))
    return `No brunch on ${dayInfo(day)[2]}s. Weekdays serve breakfast and lunch; weekends serve brunch instead of lunch.`;
  if (meal === "lunch" && isWeekend(day))
    return "Weekends serve brunch, not lunch, so there is no lunch menu to preview.";
  return null;
}

/** Default meal and date: the next scheduled text, else today's dinner. */
export function defaultPreviewChoice(form: FormState, now: ZonedNow): { meal: Meal; date: string } {
  const next = nextScheduled(form.days, now);
  return next ? { meal: next.meal, date: next.date } : { meal: "dinner", date: now.date };
}

export function isPreviewable(meal: string, date: string): meal is Meal {
  return (MEALS as string[]).includes(meal) && isIsoDate(date);
}

/**
 * ntfy publish URL. The browser POSTs a plain-text body with no custom
 * headers, so it is a CORS "simple request" and needs no preflight.
 */
export function ntfyPublishUrl(topic: string, title: string, tags: string[]): string {
  const query = [`title=${encodeURIComponent(title)}`];
  if (tags.length) query.push(`tags=${encodeURIComponent(tags.join(","))}`);
  return `https://ntfy.sh/${encodeURIComponent(topic)}?${query.join("&")}`;
}

export const TEST_COOLDOWN_MS = 5000;
