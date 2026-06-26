import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";

const PRETTY: Record<string, string> = {
  pdf_metadata: "PDF Metadata",
  font_spacing: "Font & Spacing",
  signature_region: "Signature",
  stamp_auth: "Stamp Auth",
  bank_statement: "Bank Analysis",
  ela: "ELA",
  mantranet: "ManTraNet",
};

/** SHAP: positive = pushes toward fraud (red), negative = toward clean (green). */
export function ShapChart({ contributions }: { contributions: Record<string, number> }) {
  const data = Object.entries(contributions)
    .map(([k, v]) => ({ name: PRETTY[k] || k, value: Number(v.toFixed(3)) }))
    .filter((d) => Math.abs(d.value) > 0.0001)
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));

  if (!data.length) {
    return <p className="text-sm text-muted-foreground">No SHAP attribution available.</p>;
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={Math.max(140, data.length * 34)}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 30 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={90}
            tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} />
          <Tooltip formatter={(v: number) => [v, "SHAP"]}
            contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))",
              borderRadius: 8, color: "hsl(var(--foreground))" }} />
          <Bar dataKey="value" radius={[3, 3, 3, 3]}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.value > 0 ? "#dc2626" : "#16a34a"} />
            ))}
            <LabelList dataKey="value" position="right"
              style={{ fontSize: 11, fill: "hsl(var(--foreground))" }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-muted-foreground">
        <span className="text-red-600">Red →</span> pushes toward fraud · <span className="text-green-600">Green →</span> toward clean
      </p>
    </div>
  );
}
