import type { AnalyzeResponse, CaseResponse, JobResponse } from "@/types";

const POLL_MS = 1200;
const TIMEOUT_MS = 180_000;

export async function analyzeDocument(
  file: File,
  onStatus?: (s: string) => void,
): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/analyze", { method: "POST", body: form });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  const job: JobResponse = await res.json();
  onStatus?.(job.status);

  const start = Date.now();
  while (Date.now() - start < TIMEOUT_MS) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    const r = await fetch(`/api/jobs/${job.job_id}`);
    if (!r.ok) throw new Error(`Poll failed: ${r.status}`);
    const data: JobResponse = await r.json();
    onStatus?.(data.status);
    if (data.status === "completed" && data.result) return data.result;
    if (data.status === "failed") throw new Error(data.error || "Analysis failed");
  }
  throw new Error("Timed out after 3 minutes");
}

export async function createCase(applicantName: string, note: string): Promise<CaseResponse> {
  const form = new FormData();
  if (applicantName) form.append("applicant_name", applicantName);
  if (note) form.append("note", note);
  const res = await fetch("/api/cases", { method: "POST", body: form });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function addCaseDocument(caseId: string, file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/cases/${caseId}/documents`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
}

export async function getCase(caseId: string): Promise<CaseResponse> {
  const res = await fetch(`/api/cases/${caseId}`);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export interface CaseSummary {
  id: string;
  applicant_name: string | null;
  created_at: string;
  document_count: number;
  trust_score: number | null;
  risk_tier: string | null;
}

export async function getCases(): Promise<CaseSummary[]> {
  const res = await fetch("/api/cases");
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export interface AuditEntry {
  id: string;
  created_at: string;
  document_id: string | null;
  filename: string;
  document_type: string | null;
  trust_score: number | null;
  risk_tier: string | null;
  routing: string | null;
  scorer: string | null;
  critical_indicators: string[];
}

export async function getAudit(limit = 100): Promise<{ total: number; entries: AuditEntry[] }> {
  const res = await fetch(`/api/audit?limit=${limit}`);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export interface AuditDetail extends AuditEntry {
  job_id: string | null;
  report: AnalyzeResponse | null;
  report_available: boolean;
  decision: Record<string, unknown> | null;
}

export async function getAuditDetail(id: string): Promise<AuditDetail> {
  const res = await fetch(`/api/audit/${id}`);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}
