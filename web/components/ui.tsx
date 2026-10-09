// Small presentational pieces shared by every page.
import type { ReactNode } from "react";

export function Card({ title, action, children, className = "" }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-lg border border-line bg-card p-4 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

// State colour + icon + label: a status is never shown by colour alone
const STATUS: Record<string, { tone: "ok" | "warn" | "bad" | "info" | "neutral"; icon: string }> = {
  open: { tone: "warn", icon: "●" }, updated: { tone: "warn", icon: "●" }, reanalyze: { tone: "warn", icon: "↻" },
  pending: { tone: "neutral", icon: "…" }, in_progress: { tone: "warn", icon: "…" },
  pending_approval: { tone: "warn", icon: "⏸" }, unresolved: { tone: "warn", icon: "↻" },
  resolved: { tone: "ok", icon: "✓" }, verified: { tone: "ok", icon: "✓" }, executed: { tone: "ok", icon: "▶" },
  approved: { tone: "ok", icon: "✓" }, healthy: { tone: "ok", icon: "✓" }, up: { tone: "ok", icon: "✓" },
  escalated: { tone: "bad", icon: "⚑" }, failed: { tone: "bad", icon: "✕" }, rejected: { tone: "bad", icon: "✕" },
  down: { tone: "bad", icon: "✕" }, firing: { tone: "bad", icon: "!" }, critical: { tone: "bad", icon: "!" },
  warning: { tone: "warn", icon: "!" },
  skipped: { tone: "info", icon: "–" }, dry_run: { tone: "info", icon: "◌" }, no_action: { tone: "neutral", icon: "–" },
  llm: { tone: "info", icon: "✦" }, runbook: { tone: "neutral", icon: "≡" },
};

const TONE = {
  ok: "border-ok/40 bg-ok/10 text-ink",
  warn: "border-warn/60 bg-warn/15 text-ink",
  bad: "border-bad/50 bg-bad/10 text-ink",
  info: "border-info/40 bg-info/10 text-ink",
  neutral: "border-line bg-bg text-muted",
};
const ICON_TONE = { ok: "text-ok", warn: "text-warn", bad: "text-bad", info: "text-info", neutral: "text-muted" };

export function Badge({ status, label }: { status: string | null | undefined; label?: string }) {
  const s = STATUS[status ?? ""] ?? { tone: "neutral" as const, icon: "•" };
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${TONE[s.tone]}`}>
      <span aria-hidden className={ICON_TONE[s.tone]}>{s.icon}</span>
      {label ?? (status ?? "unknown").replace(/_/g, " ")}
    </span>
  );
}

export function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-card px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-2 text-sm text-muted">{children}</p>;
}

export function ErrorNote({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return <p className="mb-2 rounded border border-bad/40 bg-bad/10 px-3 py-2 text-xs">⚠ {error}</p>;
}

export function KV({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line/60 py-1 text-sm last:border-0">
      <span className="text-muted">{k}</span>
      <span className="tabular text-right">{v}</span>
    </div>
  );
}
