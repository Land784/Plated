import { createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

import { MISSING_ENV, supabaseEnv } from "./env";

/** A per-request server client (route handlers), reading and writing the auth cookies. */
export async function supabaseServer(): Promise<SupabaseClient> {
  const env = supabaseEnv();
  if (!env) throw new Error(MISSING_ENV);
  const store = await cookies();
  return createServerClient(env.url, env.key, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (toSet) => {
        for (const { name, value, options } of toSet) store.set(name, value, options);
      },
    },
  });
}
