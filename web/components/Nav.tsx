"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLive, usePoll } from "@/lib/live";
import type { Approval } from "@/lib/types";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/incidents", label: "Incidents" },
  { href: "/approvals", label: "Approvals" },
  { href: "/system", label: "System" },
];

function Dot({ on, label }: { on: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1" title={`${label} WebSocket ${on ? "connected" : "disconnected"}`}>
      <span className={`h-2 w-2 rounded-full ${on ? "bg-ok" : "bg-bad"}`} />
      <span>{label}</span>
    </span>
  );
}

export function Nav() {
  const path = usePathname();
  const { connected } = useLive();
  const { data: approvals } = usePoll<Approval[]>("/api/responder/approvals", 5000);
  const pending = approvals?.length ?? 0;

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-card/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="font-semibold">Intelligent DevOps</Link>
        <nav className="flex flex-wrap gap-1 text-sm">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link key={l.href} href={l.href}
                className={`rounded-md px-3 py-1.5 ${active ? "bg-ink text-card" : "text-muted hover:bg-bg hover:text-ink"}`}>
                {l.label}
                {l.href === "/approvals" && pending > 0 && (
                  <span className="ml-1.5 rounded-full bg-warn px-1.5 text-xs font-semibold text-black">{pending}</span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex gap-3 text-xs text-muted">
          <Dot on={connected.events} label="events" />
          <Dot on={connected.responses} label="responses" />
        </div>
      </div>
    </header>
  );
}
