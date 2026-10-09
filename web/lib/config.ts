// Server-side only: where the API routes find the other services.
// Compose sets the service-name URLs; the defaults work for `npm run dev` on the host.
export const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://localhost:8000";
export const RESPONDER_URL = process.env.RESPONDER_URL ?? "http://localhost:8001";
export const PROMETHEUS_URL = process.env.PROMETHEUS_URL ?? "http://localhost:9090";
export const ALERTMANAGER_URL = process.env.ALERTMANAGER_URL ?? "http://localhost:9093";
export const OLLAMA_URL = process.env.OLLAMA_URL ?? "http://localhost:11434";
export const OLLAMA_MODEL = process.env.OLLAMA_MODEL ?? "llama3.1:8b";

export async function fetchJson<T = unknown>(url: string, init?: RequestInit, timeoutMs = 4000): Promise<T> {
  const r = await fetch(url, { cache: "no-store", ...init, signal: AbortSignal.timeout(timeoutMs) });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}
