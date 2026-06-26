export type RiskTier = "GREEN" | "YELLOW" | "RED";
export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface ForensicSignal {
  name: string;
  score: number;
  passed: boolean;
  detail: string;
}

export interface AnalyzeResponse {
  document_id: string;
  filename: string;
  trust_score: number;
  risk_tier: RiskTier;
  routing: "fast_track" | "underwriter_review" | "fraud_escalation";
  signals: ForensicSignal[];
  evidence_summary: string;
  heatmap_url: string | null;
  critical_indicators: string[];
  extracted_text: string | null;
  text_extraction_method: string | null;
  document_type: string | null;
  document_display_name: string | null;
  document_category: string | null;
  classification_confidence: number;
  classification_matches: string[];
  ml_doc_type: string | null;
  ml_confidence: number;
  classifier_agreement: boolean | null;
  ml_inconclusive: boolean;
  entities: Record<string, string[]>;
  scorer: string | null;
  shap_contributions: Record<string, number>;
  llm_evidence_report: string | null;
  llm_report_source: string | null;
}

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  submitted_at: string;
  result: AnalyzeResponse | null;
  error: string | null;
}

export interface CaseDocumentSummary {
  id: string;
  filename: string;
  status: string;
  document_type: string | null;
  trust_score: number | null;
  risk_tier: string | null;
  entities: Record<string, string[]> | null;
}

export interface ConsistencyFinding {
  field: string;
  severity: string;
  detail: string;
}

export interface CrossDocConsistency {
  consistency_score: number;
  passed: boolean;
  critical: boolean;
  findings: ConsistencyFinding[];
  note?: string | null;
}

export interface CaseResponse {
  id: string;
  applicant_name: string | null;
  note: string | null;
  documents: CaseDocumentSummary[];
  consistency: CrossDocConsistency | null;
}
