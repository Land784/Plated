"use client";

import { useEffect, useMemo, useState } from "react";

import {
  PREVIEW_ENDPOINT,
  buildPreviewRequest,
  isPreviewable,
  parsePreviewResponse,
  servedReason,
  type PreviewResult,
} from "@/lib/plated/preview";

import { useApp, type PreviewChoice } from "./app-provider";

export const PREVIEW_DEBOUNCE_MS = 350;

type Outcome = { key: string; result: PreviewResult } | { key: string; error: string };

export type PreviewState = {
  /** The latest result (possibly for an older request while `busy`). */
  result: PreviewResult | null;
  error: string | null;
  busy: boolean;
};

/**
 * Render the current (unsaved) form for `choice` through the preview
 * function, debounced. Meals a hall never serves that day are answered
 * locally without a request.
 */
export function usePreview(choice: PreviewChoice): PreviewState {
  const { draft, catalog } = useApp();
  const local = isPreviewable(choice.meal, choice.date) ? servedReason(choice.meal, choice.date) : "Pick a meal and date.";
  const key = useMemo(
    () => (local ? null : JSON.stringify(buildPreviewRequest(draft, catalog, choice.meal, choice.date))),
    [local, draft, catalog, choice.meal, choice.date],
  );
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (!key) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(PREVIEW_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: key,
          signal: ctrl.signal,
        });
        const json: unknown = await res.json().catch(() => null);
        if (res.status === 429) {
          setOutcome({ key, error: "Too many previews in a minute. Wait a moment and try again." });
        } else if (res.ok || (json && typeof json === "object" && (json as { sent?: unknown }).sent === false)) {
          setOutcome({ key, result: parsePreviewResponse(json) });
        } else {
          setOutcome({ key, error: "The preview isn’t available right now." });
        }
      } catch {
        if (!ctrl.signal.aborted) setOutcome({ key, error: "Couldn’t reach the preview. Check your connection." });
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [key]);

  if (local) return { result: { sent: false, reason: local }, error: null, busy: false };
  const current = outcome && outcome.key === key;
  return {
    result: outcome && "result" in outcome ? outcome.result : null,
    error: current && "error" in outcome ? outcome.error : null,
    busy: !current,
  };
}
