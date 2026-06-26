import { AlertTriangle } from "lucide-react";

export function CriticalAlert({ indicators }: { indicators: string[] }) {
  if (!indicators.length) return null;
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-500/40 dark:bg-red-500/10">
      <div className="mb-2 flex items-center gap-2 text-red-700 dark:text-red-300">
        <AlertTriangle className="h-4 w-4" />
        <span className="text-sm font-semibold">Critical Forgery Indicators (spec §7 RED override)</span>
      </div>
      <ul className="space-y-1 text-sm text-red-800 dark:text-red-200">
        {indicators.map((c, i) => (
          <li key={i} className="flex gap-2"><span aria-hidden>•</span><span>{c}</span></li>
        ))}
      </ul>
    </div>
  );
}
