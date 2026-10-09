"use client";

// Actions the policy validator held for a human: risky actions (cache flush,
// resource changes) and plans below the confidence threshold. Approving sends
// the decision to the responder, which still runs it through the executor's
// own allowlist check; rejecting hands the incident to a person.
import Link from "next/link";
import { useState } from "react";
import { Badge, Empty, ErrorNote } from "./ui";
import { actionLabel, ago, fmtNum } from "@/lib/format";
import { usePoll } from "@/lib/live";
import type { Approval } from "@/lib/types";

export function ApprovalQueue({ detailed = false }: { detailed?: boolean }) {
  const { data, error, reload } = usePoll<Approval[]>("/api/responder/approvals", 3000);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function decide(id: string, verdict: "approve" | "reject") {
    if (verdict === "approve" && !window.confirm(`Approve and execute ${id}?`)) return;
    setBusy(id);
    try {
      const r = await fetch(`/api/responder/approvals/${encodeURIComponent(id)}/${verdict}`, {
        method: "POST", headers: { "x-dashboard": "1" },
      });
      const body = await r.json().catch(() => ({}));
      setResult(r.ok ? `${id}: ${body.result ?? verdict + "d"}` : `${id}: ${body.error ?? `HTTP ${r.status}`}`);
    } catch (e) {
      setResult(`${id}: ${e}`);
    } finally {
      setBusy(null);
      reload();
    }
  }

  return (
    <div>
      <ErrorNote error={error && `Responder unreachable: ${error}`} />
      {result && <p className="mb-2 text-xs text-muted">{result}</p>}
      {!data?.length ? (
        <Empty>Nothing waiting for approval.</Empty>
      ) : (
        <div className="space-y-2">
          {data.map((a) => (
            <div key={a.approval_id} className="rounded-md border border-warn/60 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <b>{actionLabel(a.action)}</b>
                <Badge status="pending_approval" />
              </div>
              <div className="mt-1 text-xs text-muted">
                <Link className="font-mono hover:underline" href={`/incidents/${encodeURIComponent(a.plan.incident_id)}`}>{a.plan.incident_id}</Link>
                {" · "}{a.approval_id}{a.created_at ? ` · ${ago(a.created_at)}` : ""}
              </div>
              <p className="mt-1 text-sm"><span className="text-muted">Why held: </span>{a.reason ?? "–"}</p>
              {detailed && (
                <div className="mt-1 text-sm text-muted">
                  Root cause {a.plan.root_cause_service ?? "?"} · {a.plan.source} · confidence {fmtNum(a.plan.confidence ?? null, 2)}
                  {a.plan.probable_cause && <p className="mt-1 text-ink">{a.plan.probable_cause}</p>}
                </div>
              )}
              <div className="mt-2 flex gap-2">
                <button disabled={busy === a.approval_id} onClick={() => decide(a.approval_id, "approve")}
                  className="rounded-md border border-ok px-3 py-1 text-sm font-medium hover:bg-ok/10 disabled:opacity-50">
                  ✓ Approve
                </button>
                <button disabled={busy === a.approval_id} onClick={() => decide(a.approval_id, "reject")}
                  className="rounded-md border border-bad px-3 py-1 text-sm font-medium hover:bg-bad/10 disabled:opacity-50">
                  ✕ Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
