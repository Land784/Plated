"use client";

import { LoaderCircle } from "lucide-react";
import { useState } from "react";

import { useApp } from "@/components/plated/app-provider";
import { Callout, PageTitle, Seg } from "@/components/plated/bits";
import { useEditSession } from "@/components/plated/use-edit-session";
import { Button } from "@/components/ui/button";
import { CardSection } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { sameSettings } from "@/lib/plated/form";
import {
  ALLERGENS,
  LIMITS,
  NUTRIENTS,
  NUTRIENT_LABEL,
  nutritionErrors,
  type Nutrition,
  type Picks,
} from "@/lib/plated/nutrition";

function NumField({
  id,
  label,
  hint,
  value,
  onChange,
  range,
  invalid,
  placeholder,
}: {
  id: string;
  label: string;
  hint?: string;
  value: number | null;
  onChange: (v: number | null) => void;
  range: readonly [number, number];
  invalid: boolean;
  placeholder?: string;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        min={range[0]}
        max={range[1]}
        placeholder={placeholder}
        value={value === null || Number.isNaN(value) ? "" : value}
        aria-invalid={invalid || undefined}
        aria-describedby={hint ? `${id}Hint` : undefined}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
      {hint || invalid ? (
        <p id={`${id}Hint`} className={`text-xs ${invalid ? "text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>
          {invalid ? `Enter ${range[0]}–${range[1]}.` : hint}
        </p>
      ) : null}
    </div>
  );
}

export default function NutritionPage() {
  const { draft, setDraft, saved, catalog, save, resetDraft } = useApp();
  const [saving, setSaving] = useState(false);
  const dirty = !sameSettings(draft, saved, catalog);
  useEditSession(dirty);

  const n = draft.nutrition;
  const errors = nutritionErrors(n);
  const set = (update: (n: Nutrition) => Nutrition) => setDraft((f) => ({ ...f, nutrition: update(f.nutrition) }));
  const setPicks = (p: Partial<Picks>) => set((x) => ({ ...x, picks: { ...x.picks, ...p } }));
  // A cleared required field is NaN: invalid, so Save stays off until it's filled.
  const required = (v: number | null) => v ?? NaN;
  const noTargets = NUTRIENTS.every((k) => n.targets[k] === null);

  return (
    <>
      <div className="space-y-4 p-4 pb-6">
        <PageTitle title="Nutrition" hint="A plate per hall for each text: one main plus up to two sides, closest to your numbers." />

        <CardSection className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold leading-tight">Plate picks</h2>
              <p className="mt-1 text-sm text-muted-foreground">Add a suggested plate to every text.</p>
            </div>
            <Switch
              className="mt-0.5"
              checked={n.picks.enabled}
              aria-label="Plate picks"
              onCheckedChange={(enabled) => setPicks({ enabled })}
            />
          </div>
          {n.picks.enabled && noTargets ? (
            <Callout className="mt-3">Set at least one target below, or no plate is picked.</Callout>
          ) : null}
        </CardSection>

        <CardSection className="space-y-3 p-4">
          <div>
            <h2 className="text-base font-semibold leading-tight">Targets per meal</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Leave one blank to ignore it. With only protein set, sides are added just to hit protein, so set calories too.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {NUTRIENTS.map((k) => (
              <NumField
                key={k}
                id={`target-${k}`}
                label={NUTRIENT_LABEL[k]}
                value={n.targets[k]}
                range={LIMITS.target}
                invalid={errors.includes(k)}
                placeholder="—"
                onChange={(v) => set((x) => ({ ...x, targets: { ...x.targets, [k]: v } }))}
              />
            ))}
          </div>
        </CardSection>

        <CardSection className="space-y-3 p-4">
          <div>
            <h2 className="text-base font-semibold leading-tight">Allergens</h2>
            <p className="mt-1 text-sm text-muted-foreground">Picks never include these. Always confirm with dining staff.</p>
          </div>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
            {ALLERGENS.map((a) => {
              const on = n.picks.exclude_allergens.includes(a);
              return (
                <label key={a} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-current"
                    checked={on}
                    onChange={() =>
                      setPicks({
                        exclude_allergens: on
                          ? n.picks.exclude_allergens.filter((x) => x !== a)
                          : [...n.picks.exclude_allergens, a],
                      })
                    }
                  />
                  {a}
                </label>
              );
            })}
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium leading-none">Items with no allergen info</div>
            <Seg<Picks["unknown_allergens"]>
              label="Items with no allergen info"
              options={[
                ["flag", "Mark them"],
                ["exclude", "Leave them out"],
              ]}
              value={n.picks.unknown_allergens}
              onChange={(unknown_allergens) => setPicks({ unknown_allergens })}
            />
            <p className="text-xs text-muted-foreground">Missing data never means safe.</p>
          </div>
        </CardSection>

        <CardSection className="space-y-3 p-4">
          <h2 className="text-base font-semibold leading-tight">Plate rules</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <NumField
              id="tolerance"
              label="Close enough (± %)"
              hint="How far from a target still counts as hitting it."
              value={n.picks.tolerance_pct}
              range={LIMITS.tolerance_pct}
              invalid={errors.includes("tolerance_pct")}
              onChange={(v) => setPicks({ tolerance_pct: required(v) })}
            />
            <NumField
              id="mainProtein"
              label="Main: at least this protein (g)"
              hint="Also decides which dishes your station lines name."
              value={n.mainProteinG}
              range={LIMITS.mainProteinG}
              invalid={errors.includes("mainProteinG")}
              onChange={(v) => set((x) => ({ ...x, mainProteinG: required(v) }))}
            />
            <NumField
              id="sideMin"
              label="Sides: at least this many calories"
              hint="Keeps garnish and condiments out."
              value={n.picks.side_min_calories}
              range={LIMITS.side_min_calories}
              invalid={errors.includes("side_min_calories")}
              onChange={(v) => setPicks({ side_min_calories: required(v) })}
            />
            <NumField
              id="bulk"
              label="Skip items over (calories)"
              hint="Rows this big are whole pans or pizzas, not servings."
              value={n.picks.max_item_calories}
              range={LIMITS.max_item_calories}
              invalid={errors.includes("max_item_calories")}
              onChange={(v) => setPicks({ max_item_calories: required(v) })}
            />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium leading-none">Main: up to this many servings</div>
            <Seg<"1" | "2" | "3">
              label="Main servings"
              options={[
                ["1", "1"],
                ["2", "2"],
                ["3", "3"],
              ]}
              value={String(n.picks.max_main_servings) as "1" | "2" | "3"}
              onChange={(v) => setPicks({ max_main_servings: Number(v) })}
            />
          </div>
        </CardSection>
      </div>

      {dirty ? (
        <div className="sticky bottom-0 z-10 grid grid-cols-2 gap-3 border-t bg-background/95 px-4 pt-3 pb-[max(.75rem,env(safe-area-inset-bottom))] backdrop-blur md:rounded-b-3xl lg:rounded-none lg:rounded-bl-3xl">
          <Button variant="outline" size="lg" onClick={resetDraft}>
            Discard
          </Button>
          <Button
            size="lg"
            disabled={errors.length > 0 || saving}
            onClick={async () => {
              setSaving(true);
              await save(draft, "Saved");
              setSaving(false);
            }}
          >
            {saving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : null}
            Save
          </Button>
        </div>
      ) : null}
    </>
  );
}
