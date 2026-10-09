// Proxy to the responder: reads (approvals, actions, policies, health) and the
// one thing a person can do here, approve or reject a pending action. The
// responder still applies every policy check; this only forwards the decision.
import { NextResponse } from "next/server";
import { RESPONDER_URL } from "@/lib/config";

export const dynamic = "force-dynamic";

const READS = [/^approvals$/, /^actions$/, /^policies$/, /^health$/];
const WRITES = [/^approvals\/apr-\d+\/(approve|reject)$/];

async function forward(method: "GET" | "POST", path: string) {
  try {
    const r = await fetch(`${RESPONDER_URL}/${path}`, { method, cache: "no-store", signal: AbortSignal.timeout(10000) });
    return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
  } catch (e) {
    return NextResponse.json({ error: `responder unreachable: ${e}` }, { status: 502 });
  }
}

async function pathOf(ctx: { params: Promise<{ path: string[] }> }) {
  return (await ctx.params).path.map(encodeURIComponent).join("/");
}

export async function GET(_req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const path = await pathOf(ctx);
  if (!READS.some((re) => re.test(path))) return NextResponse.json({ error: "not allowed" }, { status: 404 });
  return forward("GET", path);
}

export async function POST(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  // Another site can't add a custom header without a CORS preflight, which this
  // server never allows, so a cross-site form or fetch can't approve anything.
  if (req.headers.get("x-dashboard") !== "1") return NextResponse.json({ error: "missing x-dashboard header" }, { status: 403 });
  const path = await pathOf(ctx);
  if (!WRITES.some((re) => re.test(path))) return NextResponse.json({ error: "not allowed" }, { status: 404 });
  return forward("POST", path);
}
