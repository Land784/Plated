import type { SupabaseClient } from "@supabase/supabase-js";

import { needsSetup } from "@/lib/plated/form";

/**
 * Where a freshly signed-in person goes: Setup on first run, Settings
 * otherwise. First run means the invite's row has never been written
 * since (updated_at equals created_at; Finish and every save bump it), so
 * it works on any device without a stored flag.
 */
export async function landingPath(supabase: SupabaseClient): Promise<"/setup" | "/settings"> {
  const { data } = await supabase.from("subscribers").select("created_at, updated_at").limit(1).maybeSingle();
  if (data && needsSetup({ created_at: data.created_at ?? null, updated_at: data.updated_at ?? null })) return "/setup";
  return "/settings";
}
