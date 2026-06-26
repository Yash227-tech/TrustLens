import { Badge } from "@/components/ui/badge";
import type { RiskTier } from "@/types";

const MAP: Record<RiskTier, { variant: "green" | "yellow" | "red"; label: string }> = {
  GREEN: { variant: "green", label: "GREEN · Fast-Track" },
  YELLOW: { variant: "yellow", label: "YELLOW · Underwriter Review" },
  RED: { variant: "red", label: "RED · Fraud Escalation" },
};

export function TierBadge({ tier }: { tier: RiskTier }) {
  const m = MAP[tier];
  return <Badge variant={m.variant} className="text-sm px-3 py-1">{m.label}</Badge>;
}
