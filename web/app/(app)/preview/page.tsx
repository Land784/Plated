"use client";

import { Check, LoaderCircle, RefreshCw } from "lucide-react";

import { useApp } from "@/components/plated/app-provider";
import { Callout, PageTitle, Seg } from "@/components/plated/bits";
import { ByteMeter, LockScreen, OpenedPush } from "@/components/plated/push-views";
import { usePreview } from "@/components/plated/use-preview";
import { CardSection } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MEALS, MEAL_LABEL, dayInfo, type Meal } from "@/lib/plated/constants";
import { sameSettings } from "@/lib/plated/form";
import { displayTitle, fallbackTitle } from "@/lib/plated/preview";
import { dayKeyOf, isIsoDate } from "@/lib/plated/time";

export default function PreviewPage() {
  const { draft, saved, catalog, previewChoice, setPreviewChoice } = useApp();
  const { meal, date } = previewChoice;
  const { result, error, busy } = usePreview(previewChoice);

  const validDate = isIsoDate(date);
  const day = validDate ? dayKeyOf(date) : null;
  const slot = day ? draft.days[day][meal] : undefined;
  const scheduledAt = slot?.on ? slot.t : null;

  const notes: string[] = [];
  if (day && !scheduledAt)
    notes.push(`${MEAL_LABEL[meal]} isn’t scheduled on ${dayInfo(day)[2]}s, so this text wouldn’t be sent that day.`);
  if (!draft.active) notes.push("Texts are paused, so nothing would be sent.");

  return (
    <div className="space-y-4 p-4">
      <PageTitle title="Preview" hint="Your text, rendered by the same code that sends it." />
      <CardSection className="space-y-4 p-4">
        <div className="space-y-2">
          <div className="text-sm font-medium leading-none">Meal</div>
          <Seg<Meal>
            label="Meal"
            options={MEALS.map((m) => [m, MEAL_LABEL[m]])}
            value={meal}
            onChange={(m) => setPreviewChoice({ meal: m, date })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="pvDate">Date</Label>
          <Input
            id="pvDate"
            type="date"
            value={date}
            onChange={(e) => {
              if (e.target.value) setPreviewChoice({ meal, date: e.target.value });
            }}
          />
        </div>
      </CardSection>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{sameSettings(draft, saved, catalog) ? "From your saved settings" : "Includes your unsaved changes"}</span>
        <span className="flex items-center gap-1" aria-live="polite">
          {busy ? (
            <>
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden /> Updating…
            </>
          ) : (
            <>
              <Check className="h-3.5 w-3.5" aria-hidden /> Up to date
            </>
          )}
        </span>
      </div>
      <div className="space-y-4">
        {notes.length ? <Callout>{notes.join(" ")}</Callout> : null}
        {result?.sent && !error ? (
          <>
            <LockScreen date={date} time={scheduledAt} title={displayTitle(result.title, result.tags)} body={result.body} />
            <OpenedPush time={scheduledAt} title={displayTitle(result.title, result.tags)} body={result.body} />
            <ByteMeter bytes={result.bytes} />
            <p className="flex gap-2 text-xs text-muted-foreground">
              <RefreshCw className="mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden />
              <span>Re-renders as your settings change, saved or not. Try turning off a station or putting South first.</span>
            </p>
          </>
        ) : (
          <div className="rounded-xl border border-dashed p-6 text-center">
            <div className="text-sm font-medium">{fallbackTitle(meal, date)}</div>
            <p className="mt-2 text-sm text-muted-foreground">
              {error ?? (result && !result.sent ? noSendReason(result.reason) : "Loading the preview…")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/** The function's terse reasons, in plain words. */
function noSendReason(reason: string): string {
  if (reason === "no menu published")
    return "No menu is published for this meal and date yet, or none of your stations serve it, so nothing would be sent.";
  return reason;
}
