"use client";

import { Bell, Check, LoaderCircle, Smartphone } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useApp } from "@/components/plated/app-provider";
import { useSummary } from "@/components/plated/recap";
import { SetupProgress, StepBody, StepPage } from "@/components/plated/steps";
import { useEditSession } from "@/components/plated/use-edit-session";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { STEPS, STEP_NAME, stepValid } from "@/lib/plated/form";
import { nextScheduled, nextTextLabel } from "@/lib/plated/schedule";
import { zonedNow } from "@/lib/plated/time";

export default function SetupPage() {
  const { draft, setDraft, catalog, row, save } = useApp();
  const [index, setIndex] = useState(1);
  const [done, setDone] = useState(false);
  const [saving, setSaving] = useState(false);
  useEditSession(!done);

  const scrollTop = () => window.scrollTo(0, 0);

  if (done) return <Finished />;

  const step = STEPS[index - 1];
  const valid = stepValid(draft, catalog, step);

  const next = async () => {
    if (index < 3) {
      setIndex(index + 1);
      scrollTop();
      return;
    }
    setSaving(true);
    const result = await save(draft, null);
    setSaving(false);
    if (result === "ok") {
      setDone(true);
      scrollTop();
    }
  };

  return (
    <StepPage
      top={<SetupProgress step={step} index={index} />}
      footer={
        <div className="flex gap-3">
          {index > 1 ? (
            <Button
              variant="outline"
              size="lg"
              className="w-28"
              onClick={() => {
                setIndex(index - 1);
                scrollTop();
              }}
            >
              Back
            </Button>
          ) : null}
          <Button size="lg" className="flex-1" disabled={!valid || saving} onClick={next}>
            {saving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {index === 3 ? "Finish" : "Next"}
          </Button>
        </div>
      }
    >
      <StepBody step={step} form={draft} setForm={setDraft} catalog={catalog} timezone={row.timezone} />
    </StepPage>
  );
}

function Finished() {
  const { saved, row } = useApp();
  const lines = useSummary(saved);
  const [next] = useState(() => nextScheduled(saved.days, zonedNow(row.timezone)));

  return (
    <div className="space-y-6 p-6">
      <div className="pt-6 text-center">
        <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-full bg-success/15 text-success">
          <Check className="h-7 w-7" aria-hidden />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">You’re set.</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {next ? (
            <>
              Your first text comes at <span className="font-medium text-foreground">{nextTextLabel(next)}</span>.
            </>
          ) : (
            "No meals are picked, so no texts are scheduled."
          )}
        </p>
      </div>
      <Card className="divide-y">
        {STEPS.map((k) => (
          <div key={k} className="px-4 py-3">
            <div className="text-xs text-muted-foreground">{STEP_NAME[k]}</div>
            <div className="text-sm font-medium">{lines[k][0]}</div>
          </div>
        ))}
      </Card>
      <div className="grid gap-2">
        <Button asChild size="lg" className="w-full">
          <Link href="/connect">
            <Smartphone aria-hidden /> Connect your phone
          </Link>
        </Button>
        <Button asChild variant="outline" size="lg" className="w-full">
          <Link href="/preview">
            <Bell aria-hidden /> See a preview
          </Link>
        </Button>
      </div>
      <p className="text-center text-xs text-muted-foreground">
        Texts need your phone connected first. You can change any of this in Settings.
      </p>
    </div>
  );
}
