"use client";

import { Check, Copy, ExternalLink, Eye, EyeOff, LoaderCircle, Send } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { useApp } from "@/components/plated/app-provider";
import { PageTitle, Seg } from "@/components/plated/bits";
import { usePreview } from "@/components/plated/use-preview";
import { Button } from "@/components/ui/button";
import { CardSection } from "@/components/ui/card";
import { TEST_COOLDOWN_MS, displayTitle, fallbackTitle, ntfyPublishUrl } from "@/lib/plated/preview";

const APP_STORE = "https://apps.apple.com/app/ntfy/id1625396347";
const GOOGLE_PLAY = "https://play.google.com/store/apps/details?id=io.heckel.ntfy";

type Platform = "ios" | "android";

/** The topic with everything after "plated-" masked. */
function maskTopic(topic: string): string {
  const prefix = topic.startsWith("plated-") ? "plated-" : "";
  return prefix + "•".repeat(Math.max(8, topic.length - prefix.length));
}

const isAndroid = () => /android/i.test(navigator.userAgent);

export default function ConnectPage() {
  const { row } = useApp();
  const detected = useSyncExternalStore<Platform>(
    () => () => {},
    () => (isAndroid() ? "android" : "ios"),
    () => "ios",
  );
  const [picked, setPicked] = useState<Platform | null>(null);
  const platform = picked ?? detected;

  return (
    <div className="space-y-4 p-4">
      <PageTitle
        title="Connect your phone"
        hint="Texts arrive through the free ntfy app. Subscribe once to your private topic."
      />
      <TopicCard topic={row.ntfy_topic} />
      <CardSection className="overflow-hidden">
        <div className="space-y-3 p-4 pb-0">
          <h2 className="text-base font-semibold leading-tight">Set up ntfy</h2>
          <Seg<Platform>
            label="Phone type"
            options={[
              ["ios", "iPhone"],
              ["android", "Android"],
            ]}
            value={platform}
            onChange={setPicked}
          />
        </div>
        <ol className="space-y-4 p-4">
          {(platform === "ios" ? iosSteps() : androidSteps(row.ntfy_topic)).map((s, i) => (
            <li key={i} className="flex gap-3">
              <span className="grid h-6 w-6 flex-none place-items-center rounded-full border text-xs font-medium tabular-nums">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1 pt-0.5 text-sm">{s}</div>
            </li>
          ))}
        </ol>
        {platform === "android" ? (
          <p className="border-t px-4 py-3 text-xs text-muted-foreground">
            Button didn’t open ntfy? Tap + in ntfy and paste your topic instead.
          </p>
        ) : null}
      </CardSection>
      <TestCard topic={row.ntfy_topic} />
    </div>
  );
}

function TopicCard({ topic }: { topic: string }) {
  const [reveal, setReveal] = useState(false);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(topic);
    } catch {
      setReveal(true); // fall back to showing it, so it can be selected by hand
      return;
    }
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1600);
  };

  return (
    <CardSection className="space-y-3 p-4">
      <div>
        <h2 className="text-base font-semibold leading-tight">Your topic</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Treat it like a password: anyone who has it can read your texts or send fake ones.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <code className="flex h-10 min-w-0 flex-1 items-center truncate rounded-md border bg-muted/50 px-3 font-mono text-sm tracking-tight select-all">
          {reveal ? topic : maskTopic(topic)}
        </code>
        <Button
          variant="outline"
          size="icon"
          className="h-10 w-10"
          aria-label={reveal ? "Hide topic" : "Show topic"}
          aria-pressed={reveal}
          onClick={() => setReveal(!reveal)}
        >
          {reveal ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
        </Button>
        <Button variant="outline" className="h-10 px-3" onClick={copy}>
          {copied ? (
            <>
              <Check aria-hidden /> Copied
            </>
          ) : (
            <>
              <Copy aria-hidden /> Copy
            </>
          )}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">Server: ntfy.sh (the default). The topic can’t be changed here.</p>
    </CardSection>
  );
}

const storeLink = (href: string, label: string) => (
  <a
    href={href}
    target="_blank"
    rel="noopener noreferrer"
    className="ml-1 inline-flex items-center gap-1 font-medium underline underline-offset-2"
  >
    {label} <ExternalLink className="h-3 w-3" aria-hidden />
  </a>
);

function iosSteps(): ReactNode[] {
  return [
    <>
      Install <span className="font-medium">ntfy</span> from the App Store. {storeLink(APP_STORE, "App Store")}
    </>,
    <>
      Open ntfy and tap{" "}
      <span className="inline-grid h-5 w-5 place-items-center rounded-full border font-medium leading-none">+</span> in
      the top corner.
    </>,
    <>
      Paste your topic (tap <span className="font-medium">Copy</span> above), leave the server as ntfy.sh, and tap{" "}
      <span className="font-medium">Subscribe</span>.
    </>,
    "Allow notifications when iOS asks. Then send a test below.",
  ];
}

function androidSteps(topic: string): ReactNode[] {
  return [
    <>
      Install <span className="font-medium">ntfy</span> from Google Play or F-Droid. {storeLink(GOOGLE_PLAY, "Google Play")}
    </>,
    <>
      Tap the button to subscribe in one step:
      <Button asChild className="mt-2 w-full">
        <a href={`ntfy://ntfy.sh/${encodeURIComponent(topic)}`}>Open in ntfy</a>
      </Button>
    </>,
    <>
      Confirm <span className="font-medium">Subscribe</span> in ntfy, then send a test below.
    </>,
  ];
}

type TestState = { status: "idle" } | { status: "sending" } | { status: "sent"; at: string } | { status: "failed" };

function TestCard({ topic }: { topic: string }) {
  const { previewChoice } = useApp();
  const preview = usePreview(previewChoice);
  const [test, setTest] = useState<TestState>({ status: "idle" });
  const [coolingDown, setCoolingDown] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const push = preview.result?.sent && !preview.busy ? preview.result : null;
  const title = push ? displayTitle(push.title, push.tags) : fallbackTitle(previewChoice.meal, previewChoice.date);

  const send = async () => {
    if (coolingDown || test.status === "sending") return;
    // ntfy.sh allows a burst, then one message per 5 seconds per IP: at most one test per 5 s.
    setCoolingDown(true);
    timers.current.push(setTimeout(() => setCoolingDown(false), TEST_COOLDOWN_MS));
    setTest({ status: "sending" });
    const message = push
      ? { title: push.title, tags: push.tags, body: push.body }
      : {
          title: "Plated test",
          tags: ["white_check_mark"],
          body: "Your phone is connected. Menus arrive at the times you picked.",
        };
    try {
      // A plain-text body and no custom headers keep this a CORS simple request (no preflight).
      const res = await fetch(ntfyPublishUrl(topic, message.title, message.tags), { method: "POST", body: message.body });
      if (!res.ok) throw new Error(String(res.status));
      setTest({ status: "sent", at: new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) });
    } catch {
      setTest({ status: "failed" });
    }
    timers.current.push(setTimeout(() => setTest({ status: "idle" }), 6000));
  };

  const busy = test.status === "sending";
  return (
    <CardSection className="space-y-3 p-4">
      <div>
        <h2 className="text-base font-semibold leading-tight">Send a test</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {push ? (
            <>
              Sends your current preview, <span className="font-medium text-foreground">{title}</span>, to your topic now.
              Works while paused.
            </>
          ) : preview.busy ? (
            "Getting your current preview…"
          ) : (
            <>
              There’s no menu to preview for <span className="font-medium text-foreground">{title}</span>, so this sends a
              short test message instead. Works while paused.
            </>
          )}
        </p>
      </div>
      <Button
        variant={test.status === "sent" ? "secondary" : "default"}
        className="w-full"
        disabled={busy || coolingDown || preview.busy}
        onClick={send}
      >
        {busy ? (
          <>
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Sending…
          </>
        ) : test.status === "sent" ? (
          <>
            <Check aria-hidden /> Sent
          </>
        ) : (
          <>
            <Send aria-hidden /> Send a test text
          </>
        )}
      </Button>
      <p
        className={`min-h-[1.25rem] text-center text-xs ${
          test.status === "sent" ? "text-success" : test.status === "failed" ? "text-destructive" : "text-muted-foreground"
        }`}
        aria-live="polite"
      >
        {test.status === "sent"
          ? `Sent at ${test.at}. Check your phone; nothing after a minute means the topic doesn’t match.`
          : test.status === "failed"
            ? "Couldn’t reach ntfy.sh. Check your connection, wait a few seconds and try again."
            : "Comes from your browser straight to ntfy.sh."}
      </p>
    </CardSection>
  );
}
