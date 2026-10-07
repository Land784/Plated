"use client";

import { LoaderCircle, Mail } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { OTP_INPUT_MAX_LENGTH, normalizeOtpCode } from "@/lib/plated/otp";
import { supabaseBrowser } from "@/lib/supabase/client";
import { landingPath } from "@/lib/supabase/landing";

import { Logo } from "./bits";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function SignIn() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [error, setError] = useState(params.get("error") === "link" ? "That link has expired or was already used. Send yourself a new one." : "");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const value = email.trim();
    if (!EMAIL_RE.test(value)) {
      setError("Enter the email your invite was sent to.");
      document.getElementById("email")?.focus();
      return;
    }
    setError("");
    setBusy(true);
    try {
      // Public signups are off, so an address without an invite gets no email.
      // The reply is the same either way, so nobody can test which emails have accounts.
      await supabaseBrowser().auth.signInWithOtp({
        email: value,
        options: { shouldCreateUser: false, emailRedirectTo: `${window.location.origin}/auth/confirm` },
      });
    } catch {
      // Same message on purpose.
    }
    setBusy(false);
    setSent(true);
  };

  if (sent) return <CheckEmail email={email.trim()} onReset={() => setSent(false)} />;

  return (
    <div className="flex min-h-[70vh] flex-col justify-center p-6">
      <div className="mb-8 text-center">
        <Logo size="lg" />
        <h1 className="text-2xl font-semibold tracking-tight">Sign in to Plated</h1>
        <p className="mt-1 text-sm text-muted-foreground">Notre Dame dining menus, texted to your phone.</p>
      </div>
      <form className="space-y-3" onSubmit={submit} noValidate>
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="you@nd.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-describedby="emailErr"
          aria-invalid={error ? true : undefined}
        />
        <p id="emailErr" className={`text-sm text-red-600 dark:text-red-400 ${error ? "" : "hidden"}`}>
          {error}
        </p>
        <Button className="w-full" type="submit" disabled={busy}>
          {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : <Mail aria-hidden />} Send me a link
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Plated is invite-only. Use the email your invite was sent to; no password needed.
      </p>
    </div>
  );
}

/** "Check your email", plus the code from the same email for when a link scanner used up the link. */
function CheckEmail({ email, onReset }: { email: string; onReset: () => void }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const verify = async (e: FormEvent) => {
    e.preventDefault();
    const token = normalizeOtpCode(code);
    if (!token) {
      setError("Enter the code from the email.");
      return;
    }
    setBusy(true);
    const supabase = supabaseBrowser();
    // A sign-in email's code is type "email"; an invite email's is type "invite".
    let { error: err } = await supabase.auth.verifyOtp({ email, token, type: "email" });
    if (err) ({ error: err } = await supabase.auth.verifyOtp({ email, token, type: "invite" }));
    if (err) {
      setBusy(false);
      setError("That code didn’t work. It may have expired; send a new link.");
      return;
    }
    router.replace(await landingPath(supabase));
  };

  return (
    <div className="flex min-h-[70vh] flex-col justify-center p-6">
      <Card className="p-6 text-center">
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-muted">
          <Mail className="h-5 w-5" aria-hidden />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">Check your email</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          If <span className="font-medium text-foreground">{email}</span> has a Plated invite, a sign-in link is on its way.
          Open it on this phone.
        </p>
        <form className="mt-6 space-y-2 text-left" onSubmit={verify} noValidate>
          <Label htmlFor="code" className="text-muted-foreground">
            Or enter the code from the email
          </Label>
          <div className="flex gap-2">
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={OTP_INPUT_MAX_LENGTH}
              placeholder="12345678"
              className="font-mono tracking-widest"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              aria-describedby="codeErr"
              aria-invalid={error ? true : undefined}
            />
            <Button type="submit" variant="secondary" disabled={busy}>
              {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
              Verify
            </Button>
          </div>
          <p id="codeErr" className={`text-sm text-red-600 dark:text-red-400 ${error ? "" : "hidden"}`}>
            {error}
          </p>
        </form>
        <div className="mt-6 grid gap-2">
          <Button variant="outline" className="w-full" onClick={onReset}>
            Use a different email
          </Button>
        </div>
      </Card>
    </div>
  );
}
