import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { supabaseEnv } from "./env";

/** Pages that need a signed-in person. */
const APP_PATHS = ["/setup", "/settings", "/preview", "/connect"];

const isAppPath = (path: string) => APP_PATHS.some((p) => path === p || path.startsWith(p + "/"));

/**
 * Refresh the Supabase session cookie on every page request, send
 * signed-out visitors of app pages to sign-in, and signed-in visitors of
 * sign-in to Settings. This is an optimistic check; RLS is what protects
 * the data.
 */
export async function updateSession(request: NextRequest): Promise<NextResponse> {
  let response = NextResponse.next({ request });
  const env = supabaseEnv();
  if (!env) return response;

  const supabase = createServerClient(env.url, env.key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (toSet, headers) => {
        for (const { name, value } of toSet) request.cookies.set(name, value);
        response = NextResponse.next({ request });
        for (const { name, value, options } of toSet) response.cookies.set(name, value, options);
        for (const [key, value] of Object.entries(headers ?? {})) response.headers.set(key, value);
      },
    },
  });

  // Validates the JWT (getSession alone would trust the cookie).
  const { data } = await supabase.auth.getClaims();
  const signedIn = !!data?.claims?.sub;
  const path = request.nextUrl.pathname;

  const redirect = (to: string) => {
    const url = request.nextUrl.clone();
    url.pathname = to;
    url.search = "";
    const res = NextResponse.redirect(url);
    for (const cookie of response.cookies.getAll()) res.cookies.set(cookie);
    return res;
  };

  if (!signedIn && isAppPath(path)) return redirect("/");
  if (signedIn && path === "/") return redirect("/settings");
  return response;
}
