"use client";

import { Check, ChevronDown, Star } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { DAYS, HALL_LABEL, MEAL_LABEL, type DayKey, type Meal } from "@/lib/plated/constants";
import { STEP_NAME, formHallOrder, type FormState, type StepKey } from "@/lib/plated/form";
import type { HallChoice } from "@/lib/plated/halls";
import {
  CHIPS,
  breakfastScheduled,
  chipState,
  daySummary,
  mealsFor,
  oddDays,
  setChipTime,
  setSlot,
  toggleChip,
  type Chip,
  type ChipState,
} from "@/lib/plated/schedule";
import {
  isBowlsGroup,
  toggleFavorite,
  toggleStation,
  visibleStations,
  type CatalogStation,
} from "@/lib/plated/stations";
import { zoneLabel } from "@/lib/plated/time";

import { Callout, PageTitle, SectionLabel, Seg } from "./bits";

type StepProps = {
  form: FormState;
  setForm: (update: (f: FormState) => FormState) => void;
  catalog: CatalogStation[];
  timezone: string;
};

export function StepBody({ step, ...props }: StepProps & { step: StepKey }) {
  if (step === "where") return <StepWhere {...props} />;
  if (step === "when") return <StepWhen {...props} />;
  return <StepWhat {...props} />;
}

/** One page for a wizard step (Setup) or a single-step edit (Settings > Edit); only the frame differs. */
export function StepPage({ top, footer, children }: { top: ReactNode; footer: ReactNode; children: ReactNode }) {
  return (
    <>
      <div className="space-y-5 p-4 pb-6">
        {top}
        <div className="space-y-5">{children}</div>
      </div>
      <div className="sticky bottom-0 z-10 border-t bg-background/95 px-4 pt-3 pb-[max(.75rem,env(safe-area-inset-bottom))] backdrop-blur md:rounded-b-3xl">
        {footer}
      </div>
    </>
  );
}

export function SetupProgress({ step, index }: { step: StepKey; index: number }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
        <span>Step {index} of 3</span>
        <span>{STEP_NAME[step]}</span>
      </div>
      <div
        className="grid grid-cols-3 gap-1.5"
        role="progressbar"
        aria-label="Setup progress"
        aria-valuemin={1}
        aria-valuemax={3}
        aria-valuenow={index}
        aria-valuetext={`Step ${index} of 3`}
      >
        {[1, 2, 3].map((n) => (
          <div key={n} className={`h-1.5 rounded-full ${n <= index ? "bg-primary" : "bg-muted"}`} />
        ))}
      </div>
    </div>
  );
}

/* ---------- step 1: where ---------- */

function StepWhere({ form, setForm }: StepProps) {
  const option = (v: HallChoice, title: string, sub: string, mark: string) => (
    <button
      key={v}
      type="button"
      className="choice"
      role="radio"
      aria-checked={form.hallChoice === v}
      onClick={() => setForm((f) => ({ ...f, hallChoice: v }))}
    >
      <span className="grid h-11 w-11 flex-none place-items-center rounded-lg bg-muted text-sm font-semibold tracking-tight">
        {mark}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-base font-semibold">{title}</span>
        <span className="block text-sm text-muted-foreground">{sub}</span>
      </span>
      <span className="radio" aria-hidden />
    </button>
  );
  return (
    <>
      <PageTitle
        title="Where do you usually eat?"
        hint="North and South cook different food. We’ll text you what’s on where you eat."
      />
      <div className="grid gap-3" role="radiogroup" aria-label="Where you eat">
        {option("N", "North", "North Dining Hall", "N")}
        {option("S", "South", "South Dining Hall", "S")}
        {option("both", "Both", "Both menus in one text", "N+S")}
      </div>
      {form.hallChoice === "both" ? (
        <div className="space-y-3 rounded-xl border p-4">
          <div>
            <div className="text-sm font-medium">Which first?</div>
            <p className="text-xs text-muted-foreground">It goes at the top of your text.</p>
          </div>
          <Seg
            label="Which first"
            options={[
              ["N", "North"],
              ["S", "South"],
            ]}
            value={form.first}
            onChange={(first) => setForm((f) => ({ ...f, first }))}
          />
        </div>
      ) : null}
    </>
  );
}

/* ---------- step 2: when ---------- */

function chipSub(c: Chip, cs: ChipState): string {
  return c.when + (cs.varies ? " · different on some days" : "");
}

function StepWhen({ form, setForm, timezone }: StepProps) {
  const [daysOpen, setDaysOpen] = useState(false);
  const [openDays, setOpenDays] = useState<Set<DayKey>>(new Set());
  const states = CHIPS.map((c) => [c, chipState(form.days, c)] as const);
  const chosen = states.filter(([, cs]) => cs.on);
  const odd = oddDays(form.days);
  const setDays = (fn: (d: FormState["days"]) => FormState["days"]) => setForm((f) => ({ ...f, days: fn(f.days) }));

  return (
    <>
      <PageTitle
        title="When should we text you?"
        hint={`Pick your meals. We’ll text you what’s being served at these times (${zoneLabel(timezone)}).`}
      />
      <div className="flex flex-wrap gap-2" role="group" aria-label="Meals">
        {states.map(([c, cs]) => (
          <button
            key={c.meal}
            type="button"
            className="chip"
            aria-pressed={cs.on}
            onClick={() => setDays((d) => toggleChip(d, c.meal))}
          >
            {cs.on ? <Check className="h-4 w-4" aria-hidden /> : null}
            {c.label}
          </button>
        ))}
      </div>
      {chosen.length ? (
        <Card className="divide-y">
          {chosen.map(([c, cs]) => (
            <div key={c.meal} className="flex items-center gap-3 p-4">
              <label htmlFor={`mt-${c.meal}`} className="min-w-0 flex-1">
                <span className="block text-base font-medium">{c.label}</span>
                <span className="block text-xs text-muted-foreground">{chipSub(c, cs)}</span>
              </label>
              <Input
                id={`mt-${c.meal}`}
                type="time"
                className="h-12 w-[8.75rem] px-3 text-lg"
                value={cs.t}
                step={300}
                onChange={(e) => {
                  const t = e.target.value;
                  if (t) setDays((d) => setChipTime(d, c.meal, t));
                }}
              />
            </div>
          ))}
        </Card>
      ) : (
        <Callout>Pick at least one meal, or we won’t text you.</Callout>
      )}
      <details
        className="overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm"
        open={daysOpen}
        onToggle={(e) => setDaysOpen(e.currentTarget.open)}
      >
        <summary className="flex cursor-pointer items-center gap-3 p-4">
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">Some days are different</span>
            <span className="block text-xs text-muted-foreground">
              {odd.length ? `Changed: ${odd.join(", ")}` : "Change a time or skip a meal on one day."}
            </span>
          </span>
          <ChevronDown className="chev h-4 w-4 text-muted-foreground transition-transform" aria-hidden />
        </summary>
        <div className="divide-y border-t">
          {DAYS.map(([dk, short]) => (
            <details
              key={dk}
              open={openDays.has(dk)}
              onToggle={(e) => {
                const open = e.currentTarget.open;
                setOpenDays((s) => {
                  if (open === s.has(dk)) return s;
                  const next = new Set(s);
                  if (open) next.add(dk);
                  else next.delete(dk);
                  return next;
                });
              }}
            >
              <summary className="flex cursor-pointer items-center gap-3 px-4 py-3">
                <span className="w-9 flex-none text-sm font-medium">{short}</span>
                <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{daySummary(form.days, dk)}</span>
                <ChevronDown className="chev h-4 w-4 text-muted-foreground transition-transform" aria-hidden />
              </summary>
              <div className="divide-y border-t bg-muted/30">
                {mealsFor(dk).map((meal) => (
                  <MealRow key={meal} day={dk} meal={meal} form={form} setDays={setDays} />
                ))}
              </div>
            </details>
          ))}
        </div>
      </details>
    </>
  );
}

function MealRow({
  day,
  meal,
  form,
  setDays,
}: {
  day: DayKey;
  meal: Meal;
  form: FormState;
  setDays: (fn: (d: FormState["days"]) => FormState["days"]) => void;
}) {
  const slot = form.days[day][meal]!;
  const id = `tm-${day}-${meal}`;
  return (
    <div className="flex items-center gap-3 px-4 py-2">
      <Switch
        checked={slot.on}
        aria-label={`${MEAL_LABEL[meal]} on or off`}
        onCheckedChange={(on) => setDays((d) => setSlot(d, day, meal, { on }))}
      />
      <label htmlFor={id} className={`flex-1 text-sm ${slot.on ? "" : "text-muted-foreground"}`}>
        {MEAL_LABEL[meal]}
      </label>
      <Input
        id={id}
        type="time"
        className="h-9 w-[7.5rem] px-2 text-sm"
        value={slot.t}
        step={300}
        disabled={!slot.on}
        onChange={(e) => {
          const t = e.target.value;
          if (t) setDays((d) => setSlot(d, day, meal, { t }));
        }}
      />
    </div>
  );
}

/* ---------- step 3: what ---------- */

function HallBadge({ station }: { station: CatalogStation }) {
  return <Badge>{station.halls.length === 2 ? "Both" : HALL_LABEL[station.halls[0]]}</Badge>;
}

function StationCard({
  station,
  on,
  fav,
  flash,
  onToggle,
  onStar,
}: {
  station: CatalogStation;
  on: boolean;
  fav: boolean;
  flash: boolean;
  onToggle: () => void;
  onStar: () => void;
}) {
  return (
    <div className={`relative rounded-xl ${flash ? "flash" : ""}`}>
      <button type="button" className="stcard" aria-pressed={on} onClick={onToggle}>
        <span className="tick" aria-hidden>
          <Check className="h-3.5 w-3.5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="st-name block font-medium leading-snug">{station.name}</span>
          {isBowlsGroup(station) ? (
            <span className="st-dish mt-0.5 block text-sm font-medium text-muted-foreground">Rotates daily</span>
          ) : null}
          <span
            className={`st-dish mt-0.5 line-clamp-2 block text-sm text-muted-foreground ${
              station.dishes.length ? "" : "italic"
            }`}
          >
            {station.dishes.length ? station.dishes.join(", ") : "No recent dishes listed"}
          </span>
          <span className="mt-2 flex flex-wrap gap-1">
            <HallBadge station={station} />
            {station.breakfastOnly ? <Badge variant="warning">breakfast</Badge> : null}
          </span>
        </span>
      </button>
      <button type="button" className="star" aria-pressed={fav} aria-label={`Favorite ${station.name}`} onClick={onStar}>
        <Star className="h-5 w-5" aria-hidden />
      </button>
    </div>
  );
}

function StepWhat({ form, setForm, catalog }: StepProps) {
  const [flashId, setFlashId] = useState<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(flashTimer.current), []);

  const order = formHallOrder(form);
  const visible = visibleStations(catalog, order);
  const isOn = (id: string) => !form.stations.off.includes(id);
  const isFav = (id: string) => form.stations.favorites.includes(id);
  const favs = visible.filter((s) => isFav(s.id));
  const rest = visible.filter((s) => !isFav(s.id));
  const n = visible.filter((s) => isOn(s.id)).length;
  const hiddenNote = form.hallChoice === "both" ? "" : `${form.hallChoice === "N" ? "South" : "North"}-only stations hidden`;
  const breakfastWarning =
    breakfastScheduled(form.days) && !visible.some((s) => s.breakfastOnly && isOn(s.id)) && visible.some((s) => s.breakfastOnly);

  const card = (s: CatalogStation) => (
    <StationCard
      key={s.id}
      station={s}
      on={isOn(s.id)}
      fav={isFav(s.id)}
      flash={flashId === s.id}
      onToggle={() => setForm((f) => ({ ...f, stations: toggleStation(f.stations, s.id) }))}
      onStar={() => {
        setForm((f) => ({ ...f, stations: toggleFavorite(f.stations, s.id) }));
        setFlashId(s.id);
        clearTimeout(flashTimer.current);
        flashTimer.current = setTimeout(() => setFlashId(null), 1200);
      }}
    />
  );

  return (
    <>
      <PageTitle
        title="What do you like?"
        hint={
          <>
            Tap a station to turn it on or off. Star <Star className="-mt-0.5 inline h-3.5 w-3.5" aria-label="star" /> your
            favorites: they show first in your text.
          </>
        }
      />
      <div className="flex items-baseline justify-between text-xs text-muted-foreground">
        <span className="tabular-nums">
          {n} of {visible.length} on
        </span>
        <span>{hiddenNote}</span>
      </div>
      {visible.length === 0 ? (
        <Callout>No stations have been seen at your hall in the last two weeks. Check back once menus are published.</Callout>
      ) : null}
      {favs.length ? (
        <div className="space-y-2">
          <SectionLabel>Favorites · show first</SectionLabel>
          {favs.map(card)}
        </div>
      ) : null}
      <div className="space-y-2">
        {favs.length ? <SectionLabel>Everything else</SectionLabel> : null}
        {rest.map(card)}
      </div>
      {breakfastWarning ? (
        <Callout>
          You picked breakfast texts, but every breakfast station is off. Turn one on, or breakfast texts will be empty.
        </Callout>
      ) : null}
      {n || visible.length === 0 ? null : <Callout>Turn on at least one station, or your texts will be empty.</Callout>}
      <p className="text-xs text-muted-foreground">Breakfast stations only show up in breakfast and brunch texts.</p>
    </>
  );
}
