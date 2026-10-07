"use client";

import { Fragment } from "react";

import { Progress } from "@/components/ui/progress";
import { BYTE_BUDGET } from "@/lib/plated/constants";
import { fmt12, fmtLongDate } from "@/lib/plated/time";

import { SectionLabel } from "./bits";

function AppRow({ onGlass, time }: { onGlass: boolean; time: string | null }) {
  return (
    <div className={`mb-1 flex items-center gap-2 text-[12px] ${onGlass ? "text-black/55" : "text-muted-foreground"}`}>
      <span className="grid h-5 w-5 place-items-center rounded-[5px] bg-[#338574] text-[10px] font-bold text-white">n</span>
      <span className="flex-1 uppercase tracking-wide">ntfy</span>
      <span>{time ? fmt12(time) : "now"}</span>
    </div>
  );
}

/** Plain text with https links made tappable, as the phone does. */
function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https:\/\/[^\s]+)/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <a key={i} href={p} target="_blank" rel="noopener noreferrer">
            {p}
          </a>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

export function LockScreen({ date, time, title, body }: { date: string; time: string | null; title: string; body: string }) {
  return (
    <div>
      <div className="mb-2">
        <SectionLabel>Lock screen</SectionLabel>
      </div>
      <div className="lock rounded-3xl px-3 pb-4 pt-6">
        <div className="text-center text-white/80">
          <div className="text-[13px] font-medium">{fmtLongDate(date)}</div>
          <div className="text-6xl font-semibold leading-tight tracking-tight text-white/90 tabular-nums">
            {time ? fmt12(time, false) : "9:41"}
          </div>
        </div>
        <div className="notif mt-5 rounded-2xl px-3.5 py-3 shadow-lg">
          <AppRow onGlass time={time} />
          <div className="text-[15px] font-semibold leading-snug">{title}</div>
          <div className="clamp4 whitespace-pre-wrap text-[15px] leading-snug">{body}</div>
        </div>
      </div>
    </div>
  );
}

export function OpenedPush({ time, title, body }: { time: string | null; title: string; body: string }) {
  return (
    <div>
      <div className="mb-2">
        <SectionLabel>Opened in ntfy</SectionLabel>
      </div>
      <div className="notif-full rounded-2xl border p-4 shadow-sm">
        <AppRow onGlass={false} time={time} />
        <div className="text-[15px] font-semibold leading-snug">{title}</div>
        <div className="push-body mt-1 whitespace-pre-wrap text-[13.5px] leading-[1.45]">
          <Linkified text={body} />
        </div>
      </div>
    </div>
  );
}

export function ByteMeter({ bytes }: { bytes: number }) {
  const over = bytes > BYTE_BUDGET;
  return (
    <div className="space-y-2 rounded-xl border bg-card p-4 text-card-foreground shadow-sm">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium tabular-nums">
          {bytes.toLocaleString("en-US")} bytes{" "}
          <span className="font-normal text-muted-foreground">of {BYTE_BUDGET.toLocaleString("en-US")}</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {over ? "Over budget" : `${(BYTE_BUDGET - bytes).toLocaleString("en-US")} to spare`}
        </span>
      </div>
      <Progress
        value={(bytes / BYTE_BUDGET) * 100}
        aria-label="Text size"
        indicatorClassName={over ? "bg-amber-500" : "bg-primary"}
      />
      <p className="text-xs text-muted-foreground">
        iPhone texts are cut off past 4,000 bytes, so over 3,000 the last station lines become “+N stations”. The glance,
        link and disclaimer always stay.
      </p>
    </div>
  );
}
