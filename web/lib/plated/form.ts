// The editable form state behind Setup and Settings, and its mapping to
// and from the person's `subscribers` row.

import { HALL_LABEL, type HallKey, type HallSlug } from "./constants";
import { hallOrder, hallsFromRow, hallsToRow, type HallChoice } from "./halls";
import {
  CHIPS,
  anyMealOn,
  chipState,
  oddDays,
  scheduleFromRow,
  scheduleToRow,
  type Days,
  type RowSchedule,
} from "./schedule";
import {
  deriveFavorites,
  deriveStations,
  selectionFromRow,
  visibleStations,
  type CatalogStation,
  type StationSelection,
} from "./stations";
import { fmt12, zoneLabel } from "./time";

/** The columns the app reads. */
export const SUBSCRIBER_COLUMNS =
  "id, name, halls, stations, favorites, schedule, active, ntfy_topic, timezone, created_at, updated_at";

export type SubscriberRow = {
  id: string;
  name: string;
  halls: string[];
  stations: string[];
  favorites: string[];
  schedule: unknown;
  active: boolean;
  ntfy_topic: string;
  timezone: string;
  created_at: string | null;
  updated_at: string | null;
};

/** The columns the app writes; ntfy_topic is never among them. */
export type SubscriberUpdate = {
  name: string;
  halls: HallSlug[];
  stations: string[];
  favorites: string[];
  schedule: RowSchedule;
  active: boolean;
};

const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

/** Validate a row from PostgREST; null if it isn't one. */
export function parseSubscriberRow(raw: unknown): SubscriberRow | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.id !== "string" || typeof r.ntfy_topic !== "string") return null;
  return {
    id: r.id,
    name: typeof r.name === "string" ? r.name : "",
    halls: strings(r.halls),
    stations: strings(r.stations),
    favorites: strings(r.favorites),
    schedule: r.schedule ?? {},
    active: r.active !== false,
    ntfy_topic: r.ntfy_topic,
    timezone: typeof r.timezone === "string" && r.timezone ? r.timezone : "America/New_York",
    created_at: typeof r.created_at === "string" ? r.created_at : null,
    updated_at: typeof r.updated_at === "string" ? r.updated_at : null,
  };
}

export type FormState = {
  name: string;
  hallChoice: HallChoice;
  first: HallKey;
  days: Days;
  scheduleExtra: RowSchedule;
  stations: StationSelection;
  active: boolean;
};

export function formFromRow(row: SubscriberRow, catalog: CatalogStation[]): FormState {
  const { choice, first } = hallsFromRow(row.halls);
  const { days, extra } = scheduleFromRow(row.schedule);
  return {
    name: row.name,
    hallChoice: choice,
    first,
    days,
    scheduleExtra: extra,
    stations: selectionFromRow(row.stations, row.favorites, catalog),
    active: row.active,
  };
}

/** `subscribers.name` is unique and at most 60 characters. */
export const NAME_MAX = 60;

export function cleanName(name: string): string {
  return name.trim().slice(0, NAME_MAX).trim();
}

export function formToUpdate(form: FormState, catalog: CatalogStation[]): SubscriberUpdate {
  return {
    name: cleanName(form.name),
    halls: hallsToRow(form.hallChoice, form.first),
    stations: deriveStations(catalog, form.stations),
    favorites: deriveFavorites(catalog, form.stations),
    schedule: scheduleToRow(form.days, form.scheduleExtra),
    active: form.active,
  };
}

/** The new row after a successful update, so the app needn't refetch. */
export function applyUpdate(row: SubscriberRow, update: SubscriberUpdate): SubscriberRow {
  return { ...row, ...update };
}

export function sameSettings(a: FormState, b: FormState, catalog: CatalogStation[]): boolean {
  return JSON.stringify(formToUpdate(a, catalog)) === JSON.stringify(formToUpdate(b, catalog));
}

/**
 * First run: the invite created the row with defaults and nothing has
 * written it since. (Any update, including Finish, bumps updated_at.)
 */
export function needsSetup(row: Pick<SubscriberRow, "created_at" | "updated_at">): boolean {
  if (!row.created_at || !row.updated_at) return false;
  return new Date(row.created_at).getTime() === new Date(row.updated_at).getTime();
}

export type StepKey = "where" | "when" | "what";
export const STEPS: StepKey[] = ["where", "when", "what"];
export const STEP_NAME: Record<StepKey, string> = {
  where: "Where you eat",
  when: "When",
  what: "What you like",
};

export function formHallOrder(form: FormState): HallKey[] {
  return hallOrder(form.hallChoice, form.first);
}

export function stepValid(form: FormState, catalog: CatalogStation[], step: StepKey): boolean {
  if (step === "when") return anyMealOn(form.days);
  if (step === "what")
    return visibleStations(catalog, formHallOrder(form)).some((s) => !form.stations.off.includes(s.id));
  return true;
}

/** Summary lines for the Settings cards and the Finish recap. */
export function summaryLines(
  form: FormState,
  catalog: CatalogStation[],
  timezone: string,
): Record<StepKey, string[]> {
  const order = formHallOrder(form);
  const where =
    form.hallChoice === "both"
      ? [`${HALL_LABEL[order[0]]} first, then ${HALL_LABEL[order[1]]}`, "Both menus in one text"]
      : [`${HALL_LABEL[form.hallChoice]} only`];

  const on = CHIPS.map((c) => [c, chipState(form.days, c)] as const).filter(([, cs]) => cs.on);
  const odd = oddDays(form.days);
  const when = on.length
    ? [
        on.map(([c, cs]) => `${c.label} ${fmt12(cs.t)}`).join(" · "),
        odd.length ? `Different on ${odd.join(", ")}` : `${zoneLabel(timezone)} time`,
      ]
    : ["No texts scheduled"];

  const visible = visibleStations(catalog, order);
  const n = visible.filter((s) => !form.stations.off.includes(s.id)).length;
  const favs = visible.filter((s) => form.stations.favorites.includes(s.id)).map((s) => s.name);
  const what = [
    `${n === visible.length ? "All " + n : n + " of " + visible.length} stations`,
    favs.length ? `${favs.length} favorite${favs.length > 1 ? "s" : ""}: ${favs.join(", ")}` : "No favorites yet",
  ];
  return { where, when, what };
}
