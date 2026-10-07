/**
 * Public Supabase settings. The publishable key is meant for browsers;
 * row access is enforced by RLS. No secret key is ever used by this app.
 */
export function supabaseEnv(): { url: string; key: string } | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  return url && key ? { url, key } : null;
}

export const MISSING_ENV =
  "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY must be set (see web/.env.example).";
