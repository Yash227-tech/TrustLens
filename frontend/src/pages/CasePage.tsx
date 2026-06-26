import { useEffect, useRef, useState } from "react";
import { Loader2, Plus, ShieldCheck, ShieldAlert, ArrowLeft, Layers } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { addCaseDocument, createCase, getCase, getCases, type CaseSummary } from "@/lib/api";
import type { CaseResponse } from "@/types";

const ACCEPT =
  "application/pdf,image/png,image/jpeg,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function tierVariant(t: string | null) {
  return t === "GREEN" ? "green" : t === "YELLOW" ? "yellow" : t === "RED" ? "red" : "secondary";
}

export function CasePage() {
  const [applicant, setApplicant] = useState("");
  const [caseData, setCaseData] = useState<CaseResponse | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function loadCases() {
    try {
      setCases(await getCases());
    } catch {
      /* leave list as-is */
    }
  }
  useEffect(() => {
    loadCases();
  }, []);

  // Poll the open case while any doc is still processing.
  useEffect(() => {
    if (!caseData) return;
    const pending = caseData.documents.some((d) => d.status === "queued" || d.status === "running");
    if (!pending) return;
    const t = setTimeout(async () => {
      try {
        setCaseData(await getCase(caseData.id));
      } catch {
        /* keep last */
      }
    }, 1500);
    return () => clearTimeout(t);
  }, [caseData]);

  async function start() {
    setError(null);
    setBusy(true);
    try {
      const c = await createCase(applicant, "");
      setCaseData(c);
      setApplicant("");
      loadCases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create case");
    } finally {
      setBusy(false);
    }
  }

  async function openCase(id: string) {
    setError(null);
    setBusy(true);
    try {
      setCaseData(await getCase(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to open case");
    } finally {
      setBusy(false);
    }
  }

  async function upload(files: FileList) {
    if (!caseData) return;
    setBusy(true);
    try {
      for (const f of Array.from(files)) await addCaseDocument(caseData.id, f);
      setCaseData(await getCase(caseData.id));
      loadCases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  // ---------- LIST VIEW (no case open) ----------
  if (!caseData) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Cases</h2>
          <p className="text-sm text-muted-foreground">
            Group an applicant's documents and cross-check identity across them (spec §6).
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>New Case</CardTitle>
            <CardDescription>Create a case, then add the applicant's documents.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-md border bg-card/60 px-3 py-2 text-sm outline-none backdrop-blur focus:ring-2 focus:ring-ring"
                placeholder="Applicant name (optional)"
                value={applicant}
                onChange={(e) => setApplicant(e.target.value)}
              />
              <Button onClick={start} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create Case
              </Button>
            </div>
            {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="h-4 w-4" /> All Cases ({cases.length})
            </CardTitle>
            <CardDescription>Click a case to open its documents and cross-document report.</CardDescription>
          </CardHeader>
          <CardContent>
            {cases.length === 0 ? (
              <p className="text-sm text-muted-foreground">No cases yet — create one above.</p>
            ) : (
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
                    {cases.map((c) => (
                      <tr
                        key={c.id}
                        onClick={() => openCase(c.id)}
                        className="cursor-pointer border-b border-border last:border-0 transition-colors hover:bg-accent/50"
                      >
                        <td className="py-2.5 pr-3 font-medium">{c.applicant_name || "Unnamed applicant"}</td>
                        <td className="py-2.5 pr-3 font-mono text-xs text-muted-foreground">{c.id.slice(0, 8)}</td>
                        <td className="py-2.5 pr-3 text-muted-foreground">{c.document_count}</td>
                        <td className="py-2.5 pr-3 font-mono tabular-nums">{c.trust_score ?? "—"}</td>
                        <td className="py-2.5 pr-3"><Badge variant={tierVariant(c.risk_tier)}>{c.risk_tier || "—"}</Badge></td>
                        <td className="py-2.5 pr-3 text-xs text-muted-foreground whitespace-nowrap">
                          {new Date(c.created_at).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------- CASE WORKSPACE (a case is open) ----------
  const c = caseData.consistency;
  return (
    <div className="space-y-4">
      <Button variant="outline" size="sm" onClick={() => { setCaseData(null); loadCases(); }}>
        <ArrowLeft className="h-4 w-4" /> All cases
      </Button>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Loan Application Case</CardTitle>
            <CardDescription>
              TrustLens cross-checks identity (PAN, name, GSTIN, account) across every document — spec §6.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">{caseData.applicant_name || "Unnamed applicant"}</p>
                <p className="font-mono text-xs text-muted-foreground">{caseData.id}</p>
              </div>
              <Button size="sm" variant="outline" onClick={() => inputRef.current?.click()} disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Add document
              </Button>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => e.target.files && upload(e.target.files)}
              />
            </div>

            <div className="space-y-2">
              {caseData.documents.length === 0 && (
                <p className="text-sm text-muted-foreground">No documents yet — add the applicant's files.</p>
              )}
              {caseData.documents.map((d) => (
                <div key={d.id} className="flex items-center justify-between rounded-md border p-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{d.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {d.document_type || "…"} {d.status !== "completed" && `· ${d.status}`}
                    </p>
                  </div>
                  {d.trust_score !== null ? (
                    <Badge variant={tierVariant(d.risk_tier)}>{d.trust_score}</Badge>
                  ) : (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  )}
                </div>
              ))}
            </div>
            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          </CardContent>
        </Card>

        {c ? (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Cross-Document Consistency</CardTitle>
                {c.critical ? (
                  <Badge variant="red"><ShieldAlert className="mr-1 h-3.5 w-3.5" /> Critical</Badge>
                ) : c.passed ? (
                  <Badge variant="green"><ShieldCheck className="mr-1 h-3.5 w-3.5" /> Consistent</Badge>
                ) : (
                  <Badge variant="yellow">Review</Badge>
                )}
              </div>
              <CardDescription>Consistency score: {(c.consistency_score * 100).toFixed(0)}/100</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {c.findings.map((f, i) => (
                <div
                  key={i}
                  className={`rounded-md border p-2.5 text-sm ${
                    f.severity === "critical"
                      ? "border-red-300 bg-red-50 dark:border-red-500/40 dark:bg-red-500/10"
                      : f.severity === "warning"
                      ? "border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10"
                      : "border-green-200 bg-green-50 dark:border-green-500/40 dark:bg-green-500/10"
                  }`}
                >
                  <span className="font-semibold">{f.field}:</span> {f.detail}
                </div>
              ))}
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed">
            <CardContent className="flex h-full min-h-48 items-center justify-center p-10 text-center text-sm text-muted-foreground">
              Add at least 2 documents to a case to see the cross-document consistency report
              (PAN / name / GSTIN matched across documents).
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
