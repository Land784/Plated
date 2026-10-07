"use client";

import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, use, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Meal } from "@/lib/plated/constants";
import {
  SUBSCRIBER_COLUMNS,
  applyUpdate,
  formFromRow,
  formToUpdate,
  parseSubscriberRow,
  type FormState,
  type SubscriberRow,
} from "@/lib/plated/form";
import { defaultPreviewChoice } from "@/lib/plated/preview";
import { buildCatalog, type CatalogStation, type StationViewRow } from "@/lib/plated/stations";
import { zonedNow } from "@/lib/plated/time";
import { supabaseBrowser } from "@/lib/supabase/client";

import { BottomNav, Frame, Header } from "./frame";

export type PreviewChoice = { meal: Meal; date: string };

type AppContext = {
  email: string;
  row: SubscriberRow;
  catalog: CatalogStation[];
  /** The form as last saved. */
  saved: FormState;
  /** The form being edited (Setup, or a Settings section). Preview renders this. */
  draft: FormState;
  setDraft: (update: (f: FormState) => FormState) => void;
  /** Throw away unsaved edits. */
  resetDraft: () => void;
  /** Write a form to the row; on success it becomes both `saved` and `draft`. */
  save: (form: FormState, message?: string | null) => Promise<boolean>;
  /** Hide the bottom nav (Setup steps, an open Settings edit). */
  setChromeHidden: (hidden: boolean) => void;
  previewChoice: PreviewChoice;
  setPreviewChoice: (c: PreviewChoice) => void;
};

const Ctx = createContext<AppContext | null>(null);

export function useApp(): AppContext {
  const ctx = use(Ctx);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}

type Loaded = { email: string; row: SubscriberRow; catalog: CatalogStation[] };
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "no-row"; email: string }
  | ({ status: "ready" } & Loaded);

async function load(): Promise<LoadState | null> {
  const supabase = supabaseBrowser();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return null;
  const email = auth.user.email ?? "";
  const [sub, st] = await Promise.all([
    supabase.from("subscribers").select(SUBSCRIBER_COLUMNS).limit(1).maybeSingle(),
    supabase
      .from("stations")
      .select("station, normalized, halls, meals, last_seen, is_food, example_dishes")
      .eq("is_food", true),
  ]);
  if (sub.error || st.error) return { status: "error", message: "Couldn’t load your settings. Check your connection and reload." };
  const row = parseSubscriberRow(sub.data);
  if (!row) return { status: "no-row", email };
  return { status: "ready", email, row, catalog: buildCatalog((st.data ?? []) as StationViewRow[]) };
}

export function AppProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let live = true;
    load()
      .then((s) => {
        if (!live) return;
        if (s) setState(s);
        else router.replace("/");
      })
      .catch(() => live && setState({ status: "error", message: "Couldn’t reach Plated. Check your connection and reload." }));
    return () => {
      live = false;
    };
  }, [router]);

  const signOut = useCallback(async () => {
    await supabaseBrowser().auth.signOut();
    router.replace("/");
  }, [router]);

  if (state.status !== "ready") {
    return (
      <Frame>
        <Header onSignOut={signOut} />
        <main className="flex flex-1 flex-col justify-center p-6">
          {state.status === "loading" ? (
            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Loading…
            </div>
          ) : (
            <Card className="p-6 text-center">
              <h1 className="text-xl font-semibold tracking-tight">
                {state.status === "no-row" ? "No Plated texts on this account" : "Something went wrong"}
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {state.status === "no-row"
                  ? `${state.email || "This email"} is signed in, but it isn’t linked to a Plated subscription yet. Ask the person who invited you.`
                  : state.message}
              </p>
              <Button variant="outline" className="mt-6 w-full" onClick={() => window.location.reload()}>
                Reload
              </Button>
            </Card>
          )}
        </main>
      </Frame>
    );
  }

  return (
    <Ready key={state.row.id} loaded={state} onSignOut={signOut}>
      {children}
    </Ready>
  );
}

function Ready({ loaded, onSignOut, children }: { loaded: Loaded; onSignOut: () => void; children: ReactNode }) {
  const { email, catalog } = loaded;
  const [row, setRow] = useState(loaded.row);
  const [saved, setSaved] = useState(() => formFromRow(loaded.row, catalog));
  const [draft, setDraftState] = useState(saved);
  const [chromeHidden, setChromeHidden] = useState(false);
  const [previewChoice, setPreviewChoice] = useState<PreviewChoice>(() =>
    defaultPreviewChoice(saved, zonedNow(loaded.row.timezone)),
  );

  const setDraft = useCallback((update: (f: FormState) => FormState) => setDraftState(update), []);
  const resetDraft = useCallback(() => setDraftState(saved), [saved]);

  const save = useCallback(
    async (form: FormState, message: string | null = "Saved") => {
      const update = formToUpdate(form, catalog);
      const { data, error } = await supabaseBrowser()
        .from("subscribers")
        .update(update)
        .eq("id", row.id)
        .select(SUBSCRIBER_COLUMNS)
        .maybeSingle();
      if (error || !data) {
        toast.error("Couldn’t save. Check your connection and try again.");
        return false;
      }
      const next = parseSubscriberRow(data) ?? applyUpdate(row, update);
      const nextForm = formFromRow(next, catalog);
      setRow(next);
      setSaved(nextForm);
      setDraftState(nextForm);
      if (message) toast.success(message);
      return true;
    },
    [catalog, row],
  );

  const value = useMemo<AppContext>(
    () => ({
      email,
      row,
      catalog,
      saved,
      draft,
      setDraft,
      resetDraft,
      save,
      setChromeHidden,
      previewChoice,
      setPreviewChoice,
    }),
    [email, row, catalog, saved, draft, setDraft, resetDraft, save, previewChoice],
  );

  return (
    <Ctx value={value}>
      <Frame>
        <Header paused={!saved.active} onSignOut={onSignOut} />
        <main className="flex-1">{children}</main>
        {chromeHidden ? null : <BottomNav />}
      </Frame>
    </Ctx>
  );
}
