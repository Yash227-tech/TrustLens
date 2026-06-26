import { useEffect, useState } from "react";
import { RefreshCw, Lock, ArrowLeft, ChevronRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ResultPanel } from "@/components/ResultPanel";
import { getAudit, getAuditDetail, type AuditEntry, type AuditDetail } from "@/lib/api";

function tierVariant(t: string | null) {
  return t === "GREEN" ? "green" : t === "YELLOW" ? "yellow" : t === "RED" ? "red" : "secondary";
}

function fmtTime(s: string) {
  return new Date(s).toISOString().replace("T", " ").slice(0, 19);
}

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [detail, setDetail] = useState<AuditDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await getAudit(100);
      setEntries(data.entries);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }

  async function openDetail(id: string) {
    setDetailLoading(true);
    setError(null);
    try {
      setDetail(await getAuditDetail(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit record");
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  // ---- Detail view: full report for one record ----
  if (detail) {
    const isDecision = detail.document_type === "underwriter_decision";
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Button size="sm" variant="outline" onClick={() => setDetail(null)}>
            <ArrowLeft className="h-4 w-4" /> Back to audit trail
          </Button>
          <div className="text-right text-xs text-muted-foreground">
            <div className="font-mono">{fmtTime(detail.created_at)} UTC</div>
            <div>record {detail.id.slice(0, 8)}</div>
          </div>
        </div>

        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <CardTitle className="truncate">{detail.filename}</CardTitle>
                <CardDescription className="mt-1">
                  {isDecision
                    ? "Underwriter decision record"
                    : `Document analysis · ${detail.document_type || "unknown type"}`}
                  {detail.routing && <> · routing: {detail.routing}</>}
                </CardDescription>
              </div>
              {detail.risk_tier && (
                <Badge variant={tierVariant(detail.risk_tier)}>{detail.risk_tier}</Badge>
              )}
            </div>
          </CardHeader>
          {detail.decision && (
            <CardContent>
              <div className="rounded-md border bg-muted/40 p-3 text-sm">
                {Object.entries(detail.decision).map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <span className="w-24 shrink-0 text-xs uppercase tracking-wide text-muted-foreground">
                      {k}
                    </span>
                    <span>{String(v ?? "—")}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          )}
        </Card>

        {detail.report ? (
          // Same evidence view bankers use on the Analyze tab — signals, SHAP,
          // evidence report, heatmap, entities & extracted text.
          <ResultPanel result={detail.report} file={null} />
        ) : (
          !isDecision && (
            <Card className="border-dashed">
              <CardContent className="p-8 text-center text-sm text-muted-foreground">
                The full report was not stored for this older record. Re-run the document
                on the Analyze tab to regenerate the detailed evidence.
              </CardContent>
            </Card>
          )
        )}
      </div>
    );
  }

  // ---- List view ----
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Lock className="h-4 w-4" /> Audit Trail
            </CardTitle>
            <CardDescription>
              Append-only decision log for RBI compliance — {total} record{total === 1 ? "" : "s"}.
              Click any record to open its full report. Immutable: rows are written once per
              analysis and never modified.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {detailLoading && <p className="text-sm text-muted-foreground">Loading report…</p>}
        {!error && entries.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No records yet. Analyze a document on the Analyze tab — it will appear here.
          </p>
        )}
        {entries.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3">Time (UTC)</th>
                  <th className="py-2 pr-3">Document</th>
                  <th className="py-2 pr-3">Type</th>
                  <th className="py-2 pr-3">Score</th>
                  <th className="py-2 pr-3">Tier</th>
                  <th className="py-2 pr-3">Critical</th>
                  <th className="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr
                    key={e.id}
                    onClick={() => openDetail(e.id)}
                    className="cursor-pointer border-b last:border-0 transition-colors hover:bg-muted/50"
                  >
                    <td className="py-2 pr-3 font-mono text-xs text-muted-foreground whitespace-nowrap">
                      {fmtTime(e.created_at)}
                    </td>
                    <td className="py-2 pr-3 max-w-[220px] truncate">{e.filename}</td>
                    <td className="py-2 pr-3 text-muted-foreground">{e.document_type || "—"}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums">{e.trust_score ?? "—"}</td>
                    <td className="py-2 pr-3">
                      <Badge variant={tierVariant(e.risk_tier)}>{e.risk_tier || "—"}</Badge>
                    </td>
                    <td className="py-2 pr-3 text-xs text-red-700 dark:text-red-300">
                      {e.critical_indicators.length ? `${e.critical_indicators.length} flag(s)` : "—"}
                    </td>
                    <td className="py-2 pr-1 text-muted-foreground">
                      <ChevronRight className="h-4 w-4" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
