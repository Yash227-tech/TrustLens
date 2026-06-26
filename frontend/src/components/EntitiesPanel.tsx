import { Badge } from "@/components/ui/badge";

const LABELS: Record<string, string> = {
  pan: "PAN", gstin: "GSTIN", aadhaar: "Aadhaar", ifsc: "IFSC",
  account_number: "Account No.", amount: "Amounts", date: "Dates",
  person: "Names", org: "Organisations", location: "Locations",
};

export function EntitiesPanel({ entities }: { entities: Record<string, string[]> }) {
  const keys = Object.keys(entities).filter((k) => entities[k]?.length);
  if (!keys.length) return <p className="text-sm text-muted-foreground">No entities extracted.</p>;
  return (
    <div className="space-y-3">
      {keys.map((k) => (
        <div key={k}>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {LABELS[k] || k}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {entities[k].slice(0, 12).map((v, i) => (
              <Badge key={i} variant="secondary" className="font-mono text-xs">{v}</Badge>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
