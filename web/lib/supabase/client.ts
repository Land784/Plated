import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { MISSING_ENV, supabaseEnv } from "./env";

let client: SupabaseClient | null = null;

/** The browser client: the publishable key plus the signed-in person's session cookie. */
export function supabaseBrowser(): SupabaseClient {
  if (client) return client;
  const env = supabaseEnv();
  if (!env) throw new Error(MISSING_ENV);
  client = createBrowserClient(env.url, env.key);
  return client;
}
