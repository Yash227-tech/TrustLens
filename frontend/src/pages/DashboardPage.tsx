import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, ShieldCheck, AlertTriangle, Layers, Clock, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  getAudit, getAuditDetail, getCases,
  type AuditEntry, type AuditDetail, type CaseSummary,
} from "@/lib/api";

type Tone = "green" | "amber" | "red" | "blue";
const BAR_COLOR: Record<Tone, string> = {
  green: "bg-success", amber: "bg-warning", red: "bg-danger", blue: "bg-primary",
};
const PILL: Record<Tone, string> = {
  green: "bg-success/15 text-success",
  amber: "bg-warning/15 text-warning",
  red: "bg-danger/15 text-danger",
  blue: "bg-primary/15 text-primary",
};

function tierVariant(t: string | null) {
  return t === "GREEN" ? "green" : t === "YELLOW" ? "yellow" : t === "RED" ? "red" : "secondary";
}
function relTime(iso: string) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} hr ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function signalTone(score: number): { pct: number; tone: Tone; status: string } {
  const pct = Math.round(score * 100);
  if (pct >= 70) return { pct, tone: "green", status: "Pass" };
  if (pct >= 40) return { pct, tone: "amber", status: "Review" };
  return { pct, tone: "red", status: "Fail" };
}

function TrustGauge({ score }: { score: number }) {
  const r = 54, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 130 130" className="h-36 w-36">
      <circle cx="65" cy="65" r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth="11" />
      <circle cx="65" cy="65" r={r} fill="none" stroke="hsl(var(--primary))" strokeWidth="11" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform="rotate(-90 65 65)" />
      <text x="65" y="62" textAnchor="middle" style={{ fill: "hsl(var(--foreground))" }} className="text-[28px] font-bold">{score}</text>
      <text x="65" y="82" textAnchor="middle" style={{ fill: "hsl(var(--muted-foreground))" }} className="text-[11px]">/100</text>
    </svg>
  );
}

function SectionCard({ title, action, children, className }: {
  title: string; action?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <Card className={cn("p-5", className)}>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </Card>
  );
}

function StatCard({ icon: Icon, tint, value, label }: {
  icon: typeof FileText; tint: string; value: string | number; label: string;
}) {
  return (
    <Card className="p-5">
      <div className={cn("flex h-11 w-11 items-center justify-center rounded-xl", tint)}>
        <Icon className="h-5 w-5" />
      </div>
      <p className="mt-3 text-3xl font-bold tracking-tight">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </Card>
  );
}

export function DashboardPage() {
  const [audit, setAudit] = useState<{ total: number; entries: AuditEntry[] } | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [latest, setLatest] = useState<AuditDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [a, cs] = await Promise.all([getAudit(100), getCases()]);
        setAudit(a);
        setCases(cs);
        if (a.entries.length) {
          try { setLatest(await getAuditDetail(a.entries[0].id)); } catch { /* no detail */ }
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-64 items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading dashboard…
      </div>
    );
  }

  const entries = audit?.entries ?? [];
  const scores = entries.map((e) => e.trust_score).filter((s): s is number => s !== null);
  const avg = scores.length ? Math.round(scores.reduce((x, y) => x + y, 0) / scores.length) : 0;
  const fraud = entries.filter((e) => e.risk_tier === "RED").length;
  const report = latest?.report ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-sm text-muted-foreground">AI-Assisted Document Analysis Overview</p>
      </div>

      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}

      {/* stat cards — all real */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={FileText} tint="bg-blue-500/15 text-blue-500" value={audit?.total ?? 0} label="Documents Analyzed" />
        <StatCard icon={ShieldCheck} tint="bg-success/15 text-success" value={`${avg}/100`} label="Average Trust Score" />
        <StatCard icon={AlertTriangle} tint="bg-danger/15 text-danger" value={fraud} label="Fraud Detected (RED)" />
        <StatCard icon={Layers} tint="bg-violet-500/15 text-violet-500" value={cases.length} label="Cases" />
      </div>

      {/* latest analysis + signal results */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          <SectionCard title="Latest Analysis">
            {report ? (
              <>
                <div className="mb-4 flex items-center gap-3 text-sm">
                  <FileText className="h-4 w-4 text-primary" />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{report.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {report.document_type} · {latest && relTime(latest.created_at)}
                    </p>
                  </div>
                </div>
                <div className="flex flex-col items-center gap-3 sm:flex-row">
                  <div className="flex flex-col items-center">
                    <TrustGauge score={report.trust_score} />
                    <Badge variant={tierVariant(report.risk_tier)} className="-mt-2">{report.risk_tier}</Badge>
                  </div>
                  <div className="flex-1 rounded-xl bg-accent/40 p-3">
                    <p className="text-xs leading-relaxed text-muted-foreground line-clamp-[8]">
                      {report.llm_evidence_report || report.evidence_summary}
                    </p>
                  </div>
                </div>
                <Button className="mt-4 w-full" asChild><Link to="/audit">View Full Report</Link></Button>
              </>
            ) : (
              <EmptyHint />
            )}
          </SectionCard>

          <SectionCard title="Forgery Heatmap">
            {report?.heatmap_url ? (
              <img src={report.heatmap_url} alt="Forgery heatmap"
                className="w-full rounded-xl border border-border bg-slate-900 object-contain" />
            ) : (
              <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                No heatmap for the latest document.
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <Legend color="bg-danger" label="High Risk" />
              <Legend color="bg-warning" label="Medium Risk" />
              <Legend color="bg-success" label="Low Risk" />
            </div>
          </SectionCard>
        </div>

        <SectionCard title="Signal Results" className="lg:col-span-3">
          {report?.signals?.length ? (
            <div className="divide-y divide-border">
              {report.signals.map((s) => {
                const { pct, tone, status } = signalTone(s.score);
                return (
                  <div key={s.name} className="flex items-center gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{s.name}</p>
                      <p className="truncate text-xs text-muted-foreground">{s.detail}</p>
                    </div>
                    <div className="hidden h-1.5 w-28 overflow-hidden rounded-full bg-muted sm:block">
                      <div className={cn("h-full rounded-full", BAR_COLOR[tone])} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-9 text-right text-xs tabular-nums text-muted-foreground">{pct}%</span>
                    <span className={cn("w-16 shrink-0 rounded-md px-2 py-0.5 text-center text-xs font-semibold", PILL[tone])}>
                      {status}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyHint />
          )}
        </SectionCard>
      </div>

      {/* recent cases — real */}
      <SectionCard title="Recent Cases"
        action={<Link to="/cases" className="text-xs text-primary hover:underline">View All Cases</Link>}>
        {cases.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3">Applicant</th>
                  <th className="py-2 pr-3">Case ID</th>
                  <th className="py-2 pr-3">Documents</th>
                  <th className="py-2 pr-3">Trust Score</th>
                  <th className="py-2 pr-3">Tier</th>
                  <th className="py-2 pr-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {cases.slice(0, 6).map((c) => (
                  <tr key={c.id} className="border-b border-border last:border-0">
                    <td className="py-2.5 pr-3 font-medium">{c.applicant_name || "Unnamed applicant"}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs text-muted-foreground">{c.id.slice(0, 8)}</td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{c.document_count}</td>
                    <td className="py-2.5 pr-3 font-mono tabular-nums">{c.trust_score ?? "—"}</td>
                    <td className="py-2.5 pr-3"><Badge variant={tierVariant(c.risk_tier)}>{c.risk_tier || "—"}</Badge></td>
                    <td className="py-2.5 pr-3 text-xs text-muted-foreground whitespace-nowrap">
                      <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{relTime(c.created_at)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No cases yet. Create one on the <Link to="/cases" className="text-primary hover:underline">Cases</Link> page.
          </p>
        )}
      </SectionCard>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("h-2.5 w-2.5 rounded-full", color)} /> {label}
    </span>
  );
}

function EmptyHint() {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
      <p>No analyses yet.</p>
      <Button size="sm" variant="outline" asChild><Link to="/analyze">Analyze a document</Link></Button>
    </div>
  );
}
