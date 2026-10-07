import type { NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/proxy";

export async function proxy(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  // Pages only: not static files, not /auth/confirm (it sets its own session), not /api (the Python preview function).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|auth/|api/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
