import { Progress } from "@/components/ui/progress";
import type { ForensicSignal } from "@/types";

function color(score: number) {
  if (score >= 0.7) return "bg-green-500";
  if (score >= 0.4) return "bg-amber-500";
  return "bg-red-500";
}

export function SignalsList({ signals }: { signals: ForensicSignal[] }) {
  return (
    <div className="space-y-4">
      {signals.map((s) => (
        <div key={s.name}>
          <div className="mb-1 flex items-center justify-between gap-3">
            <span className="text-sm font-medium">{s.name}</span>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {(s.score * 100).toFixed(0)}
            </span>
          </div>
          <Progress value={s.score * 100} indicatorClassName={color(s.score)} />
          <p className="mt-1 text-xs text-muted-foreground">{s.detail}</p>
        </div>
      ))}
    </div>
  );
}
