"use client";

import { Bell, SlidersHorizontal, Smartphone } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { Logo } from "./bits";

/** The phone-width column every screen sits in. */
export function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="app-frame relative mx-auto flex min-h-[100dvh] w-full max-w-[430px] flex-col bg-background">
      {children}
    </div>
  );
}

export function Header({ paused, onSignOut }: { paused?: boolean; onSignOut?: () => void }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b bg-background/90 px-4 backdrop-blur md:rounded-t-3xl">
      <div className="flex items-center gap-2">
        <Logo />
        <span className="font-semibold tracking-tight">Plated</span>
        {paused ? <Badge className="ml-1">Paused</Badge> : null}
      </div>
      {onSignOut ? (
        <Button variant="ghost" className="h-8 px-2 text-sm text-muted-foreground" onClick={onSignOut}>
          Sign out
        </Button>
      ) : null}
    </header>
  );
}

const NAV = [
  { href: "/settings", label: "Settings", Icon: SlidersHorizontal },
  { href: "/preview", label: "Preview", Icon: Bell },
  { href: "/connect", label: "Connect", Icon: Smartphone },
] as const;

export function BottomNav() {
  const path = usePathname();
  return (
    <nav className="sticky bottom-0 z-20 grid h-16 grid-cols-3 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:rounded-b-3xl">
      {NAV.map(({ href, label, Icon }) => {
        const current = path === href;
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={`flex flex-col items-center justify-center gap-1 text-xs font-medium ${
              current ? "text-foreground" : "text-muted-foreground"
            }`}
          >
            <Icon className="h-5 w-5" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
