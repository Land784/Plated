"use client";

import { useMemo } from "react";

import { summaryLines, type FormState, type StepKey } from "@/lib/plated/form";

import { useApp } from "./app-provider";

/** Summary lines for each step, from a form (saved for Settings, draft for Finish). */
export function useSummary(form: FormState): Record<StepKey, string[]> {
  const { catalog, row } = useApp();
  return useMemo(() => summaryLines(form, catalog, row.timezone), [form, catalog, row.timezone]);
}
