"use client";

import { LoaderCircle, Pause } from "lucide-react";
import { useState } from "react";

import { useApp } from "@/components/plated/app-provider";
import { Callout, PageTitle, SectionLabel } from "@/components/plated/bits";
import { useSummary } from "@/components/plated/recap";
import { StepBody, StepPage } from "@/components/plated/steps";
import { useEditSession } from "@/components/plated/use-edit-session";
import { Button } from "@/components/ui/button";
import { CardSection } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { STEPS, STEP_NAME, stepValid, type StepKey } from "@/lib/plated/form";

export default function SettingsPage() {
  const { draft, setDraft, resetDraft, catalog, row, save } = useApp();
  const [editing, setEditing] = useState<StepKey | null>(null);
  const [flashCard, setFlashCard] = useState<StepKey | null>(null);
  const [saving, setSaving] = useState(false);
  useEditSession(editing !== null);

  if (!editing) {
    return (
      <Summary
        flashCard={flashCard}
        onEdit={(k) => {
          resetDraft();
          setFlashCard(null);
          setEditing(k);
          window.scrollTo(0, 0);
        }}
      />
    );
  }

  const close = () => {
    setEditing(null);
    window.scrollTo(0, 0);
  };

  return (
    <StepPage
      top={<SectionLabel>Settings · {STEP_NAME[editing]}</SectionLabel>}
      footer={
        <div className="grid grid-cols-2 gap-3">
          <Button
            variant="outline"
            size="lg"
            onClick={() => {
              resetDraft();
              close();
            }}
          >
            Cancel
          </Button>
          <Button
            size="lg"
            disabled={!stepValid(draft, catalog, editing) || saving}
            onClick={async () => {
              setSaving(true);
              const ok = await save(draft, "Saved");
              setSaving(false);
              if (ok) {
                setFlashCard(editing);
                close();
              }
            }}
          >
            {saving ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : null}
            Done
          </Button>
        </div>
      }
    >
      <StepBody step={editing} form={draft} setForm={setDraft} catalog={catalog} timezone={row.timezone} />
    </StepPage>
  );
}

function Summary({ flashCard, onEdit }: { flashCard: StepKey | null; onEdit: (k: StepKey) => void }) {
  const { saved, save, email } = useApp();
  const lines = useSummary(saved);
  const paused = !saved.active;
  const [name, setName] = useState(saved.name);

  const togglePause = () =>
    save({ ...saved, active: paused }, paused ? "Saved. Texts are back on." : "Saved. Texts paused.");

  const saveName = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setName(saved.name);
      return;
    }
    if (trimmed !== saved.name) void save({ ...saved, name: trimmed });
  };

  return (
    <div className="space-y-4 p-4">
      {paused ? (
        <Callout className="items-center" icon={<Pause className="h-4 w-4 flex-none" aria-hidden />}>
          <span className="flex items-center gap-2">
            <span className="flex-1">Paused. No texts until you resume.</span>
            <Button variant="outline" className="h-8 px-3 text-xs" onClick={togglePause}>
              Resume
            </Button>
          </span>
        </Callout>
      ) : null}
      <PageTitle title="Settings" hint="What your texts include, and when they arrive." />
      {STEPS.map((k) => {
        const [l1, l2] = lines[k];
        return (
          <CardSection key={k} className={`p-4 ${flashCard === k ? "flash" : ""}`}>
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{STEP_NAME[k]}</h2>
                <div className="mt-1.5 text-[15px] font-medium leading-snug">{l1}</div>
                {l2 ? <div className="mt-0.5 text-sm text-muted-foreground">{l2}</div> : null}
              </div>
              <Button variant="outline" size="sm" className="flex-none" aria-label={`Edit ${STEP_NAME[k]}`} onClick={() => onEdit(k)}>
                Edit
              </Button>
            </div>
          </CardSection>
        );
      })}
      <CardSection className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold leading-tight">Pause texts</h2>
            <p className="mt-1 text-sm text-muted-foreground">Nothing is sent while paused. Your settings are kept.</p>
          </div>
          <Switch className="mt-0.5" checked={paused} aria-label="Pause texts" onCheckedChange={togglePause} />
        </div>
      </CardSection>
      <CardSection className="space-y-3 p-4">
        <h2 className="text-base font-semibold leading-tight">Account</h2>
        <div className="space-y-2">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            value={name}
            autoComplete="nickname"
            onChange={(e) => setName(e.target.value)}
            onBlur={saveName}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
        </div>
        <div className="space-y-2">
          <div className="text-sm font-medium leading-none">Email</div>
          <div className="text-sm text-muted-foreground">
            {email} <span className="text-xs">· set by your invite</span>
          </div>
        </div>
      </CardSection>
      <p className="text-center text-xs text-muted-foreground">Changes save when you tap Done.</p>
    </div>
  );
}
