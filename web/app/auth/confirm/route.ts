import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";

import { landingPath } from "@/lib/supabase/landing";
import { supabaseServer } from "@/lib/supabase/server";

// Sign-in links and invites both land here. They carry a token hash
// (not a PKCE code), which verifyOtp exchanges for a session cookie.
// The email templates must link to:
//   {{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email   (magic link)
//   {{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=invite  (invite)
const ALLOWED: EmailOtpType[] = ["email", "invite"];

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;

  const to = (path: string) => {
    const url = request.nextUrl.clone();
    url.pathname = path;
    url.search = path === "/" ? "?error=link" : "";
    return NextResponse.redirect(url);
  };

  if (!tokenHash || !type || !ALLOWED.includes(type)) return to("/");

  try {
    const supabase = await supabaseServer();
    const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
    if (error) return to("/");
    return to(await landingPath(supabase));
  } catch {
    return to("/");
  }
}
