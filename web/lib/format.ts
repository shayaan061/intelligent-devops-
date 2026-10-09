export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return Number(v.toFixed(digits)).toString();
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}

/** Percent with as many decimals as small values need (0.5% stays 0.5%, not 1%). */
export function fmtPctAuto(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  return fmtPct(v, a === 0 || a >= 0.1 ? 0 : a >= 0.01 ? 1 : 2);
}

export function fmtSecs(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  if (v < 1) return `${Math.round(v * 1000)} ms`;
  if (v < 120) return `${v.toFixed(1)} s`;
  return `${(v / 60).toFixed(1)} min`;
}

export function fmtLatency(v: number | null | undefined): string {
  // seconds -> ms below 1 s
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return v < 1 ? `${(v * 1000).toFixed(0)} ms` : `${v.toFixed(2)} s`;
}

export function fmtBytes(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "–"
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function ago(iso?: string | null, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

export function actionLabel(a?: { type: string; target?: string | null } | null): string {
  if (!a) return "–";
  return a.target ? `${a.type} → ${a.target}` : a.type;
}
