import { ApprovalQueue } from "@/components/Approvals";
import { Card } from "@/components/ui";

export default function Approvals() {
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Approvals</h1>
      <p className="max-w-3xl text-sm text-muted">
        The policy validator holds an action for a person when it is classed as risky (flushing the cache, changing
        resource limits) or when the plan&apos;s confidence is below the threshold. Approving runs it through the
        executor, which re-checks the allowlist; rejecting stops the automation for that incident and leaves it to a person. The incident stays on hold until
        someone decides.
      </p>
      <Card><ApprovalQueue detailed /></Card>
    </div>
  );
}
