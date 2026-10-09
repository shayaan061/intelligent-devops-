"use client";

// Live state from the gateway's two WebSockets, shared by every page.
// /ws/events     incident open/updated/reanalyze/resolved (and raw alerts)
// /ws/responses  response plans and responder action records
// The gateway replays its recent buffer to each new client, so after a
// reconnect the same messages arrive again; they are de-duplicated by key.
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { IncidentMsg, StepMsg } from "./types";

interface LiveState {
  incidents: Map<string, IncidentMsg>;
  steps: Map<string, StepMsg[]>;
  connected: { events: boolean; responses: boolean };
  lastMessageAt: number | null;
  version: number;
}

const LiveContext = createContext<LiveState | null>(null);

function gatewayWsBase(): string {
  const override = process.env.NEXT_PUBLIC_GATEWAY_WS;
  if (override) return override.replace(/\/$/, "");
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:8000`;
}

function stepKey(m: StepMsg): string {
  const when = m.type === "action" ? m.at : m.created_at;
  return [m.type, m.incident_id, m.type === "action" ? m.status : "", m.attempt ?? 1, m.received_at ?? "", when ?? ""].join("|");
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const incidents = useRef(new Map<string, IncidentMsg>());
  const steps = useRef(new Map<string, StepMsg[]>());
  const seen = useRef(new Set<string>());
  const [connected, setConnected] = useState({ events: false, responses: false });
  const [version, setVersion] = useState(0);
  const [lastMessageAt, setLast] = useState<number | null>(null);

  useEffect(() => {
    let stopped = false;
    const sockets: WebSocket[] = [];
    // Batch renders: many replayed messages arrive at once
    let pending = false;
    const bump = () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => { pending = false; setVersion((v) => v + 1); setLast(Date.now()); });
    };

    const connect = (path: "/ws/events" | "/ws/responses", key: "events" | "responses", onMsg: (m: Record<string, unknown>) => void) => {
      if (stopped) return;
      const ws = new WebSocket(gatewayWsBase() + path);
      sockets.push(ws);
      ws.onopen = () => setConnected((c) => ({ ...c, [key]: true }));
      ws.onmessage = (e) => {
        try { onMsg(JSON.parse(e.data)); bump(); } catch { /* ignore malformed */ }
      };
      ws.onclose = () => {
        setConnected((c) => ({ ...c, [key]: false }));
        if (!stopped) setTimeout(() => connect(path, key, onMsg), 2000);
      };
    };

    connect("/ws/events", "events", (m) => {
      if (m.type !== "incident" || typeof m.incident_id !== "string") return;
      const inc = m as unknown as IncidentMsg;
      const prev = incidents.current.get(inc.incident_id);
      // Keep the newest state; a replayed older update must not overwrite it
      if (!prev || (inc.timestamp ?? "") >= (prev.timestamp ?? "")) incidents.current.set(inc.incident_id, inc);
    });
    connect("/ws/responses", "responses", (m) => {
      if ((m.type !== "response_plan" && m.type !== "action") || typeof m.incident_id !== "string") return;
      const s = m as unknown as StepMsg;
      const k = stepKey(s);
      if (seen.current.has(k)) return;
      seen.current.add(k);
      const list = steps.current.get(s.incident_id) ?? [];
      list.push(s);
      steps.current.set(s.incident_id, list);
    });

    return () => { stopped = true; sockets.forEach((s) => s.close()); };
  }, []);

  const value = useMemo<LiveState>(
    () => ({ incidents: incidents.current, steps: steps.current, connected, lastMessageAt, version }),
    [connected, lastMessageAt, version],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveState {
  const v = useContext(LiveContext);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}

/** Poll a JSON endpoint; returns the latest body (or null) and the last error. */
export function usePoll<T>(url: string, everyMs: number, deps: unknown[] = []): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(url, { cache: "no-store" });
        const body = await r.json();
        if (!alive) return;
        if (!r.ok) setError(body?.error ?? `HTTP ${r.status}`);
        else { setData(body as T); setError(null); }
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    load();
    const id = setInterval(load, everyMs);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, everyMs, tick, ...deps]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}
