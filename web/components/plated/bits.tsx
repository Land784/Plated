"use client";

import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Alert } from "@/components/ui/alert";

/** Segmented control (shadcn ToggleGroup type="single" look). */
export function Seg<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: [T, string][];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={v === value} onClick={() => onChange(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

export function Callout({ children, icon, className }: { children: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <Alert className={className}>
      {icon ?? <CircleAlert className="mt-0.5 h-4 w-4 flex-none" aria-hidden />}
      <span className="flex-1">{children}</span>
    </Alert>
  );
}

export function PageTitle({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {hint ? <p className="mt-1 text-sm text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{children}</div>;
}

export function Logo({ size = "sm" }: { size?: "sm" | "lg" }) {
  return size === "lg" ? (
    <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-primary text-2xl text-primary-foreground">
      🍽
    </div>
  ) : (
    <div className="grid h-7 w-7 place-items-center rounded-md bg-primary text-[15px] text-primary-foreground">🍽</div>
  );
}
