// Read-only proxy to the gateway's output endpoints (no CORS needed in the browser).
// Only GETs on an allowlist: the dashboard never posts alerts, plans or actions.
import { NextResponse } from "next/server";
import { GATEWAY_URL } from "@/lib/config";

export const dynamic = "force-dynamic";

const ALLOWED = [/^history$/, /^history\/[\w.-]+$/, /^incidents$/, /^incidents\/[\w.-]+$/, /^events$/, /^responses$/, /^health$/];

export async function GET(_req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const path = (await ctx.params).path.map(encodeURIComponent).join("/");
  if (!ALLOWED.some((re) => re.test(path))) {
    return NextResponse.json({ error: "not allowed" }, { status: 404 });
  }
  try {
    const r = await fetch(`${GATEWAY_URL}/${path}`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    return new NextResponse(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
  } catch (e) {
    return NextResponse.json({ error: `gateway unreachable: ${e}` }, { status: 502 });
  }
}
