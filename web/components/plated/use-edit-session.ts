"use client";

import { useEffect, useRef } from "react";

import { useApp } from "./app-provider";

/**
 * While `editing`, hide the bottom nav. Leaving the page with an edit open
 * discards it, as Cancel does.
 */
export function useEditSession(editing: boolean) {
  const { setChromeHidden, resetDraft } = useApp();
  const reset = useRef(resetDraft);

  useEffect(() => {
    reset.current = resetDraft;
  }, [resetDraft]);

  useEffect(() => {
    setChromeHidden(editing);
  }, [editing, setChromeHidden]);

  useEffect(
    () => () => {
      setChromeHidden(false);
      reset.current();
    },
    [setChromeHidden],
  );
}
