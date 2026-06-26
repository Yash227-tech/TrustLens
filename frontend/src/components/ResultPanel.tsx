import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { TierBadge } from "./TierBadge";
import { SignalsList } from "./SignalsList";
import { ShapChart } from "./ShapChart";
import { EntitiesPanel } from "./EntitiesPanel";
import { CriticalAlert } from "./CriticalAlert";
import { PdfHeatmapViewer } from "./PdfHeatmapViewer";
import type { AnalyzeResponse } from "@/types";

export function ResultPanel({ result, file }: { result: AnalyzeResponse; file: File | null }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="truncate">{result.filename}</CardTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {result.document_display_name && (
                <Badge variant="outline">
                  {result.document_display_name}
                  {result.document_category && result.document_category !== "unknown" && (
                    <span className="ml-1 text-muted-foreground">· {result.document_category}</span>
                  )}
                </Badge>
              )}
              {result.ml_inconclusive ? (
                <span className="font-mono text-xs text-muted-foreground">
                  LayoutLMv3: low confidence ({(result.ml_confidence * 100).toFixed(0)}%)
                </span>
              ) : result.classifier_agreement !== null ? (
                <span className="font-mono text-xs text-muted-foreground">
                  {result.classifier_agreement ? "✓ LayoutLMv3 agrees" : `⚠ LayoutLMv3: ${result.ml_doc_type}`}
                </span>
              ) : null}
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Trust Score</p>
            <p className="text-5xl font-bold tabular-nums leading-none">{result.trust_score}</p>
            <p className="mt-1 text-[10px] uppercase text-muted-foreground">scorer: {result.scorer}</p>
          </div>
        </div>
        <div className="mt-3"><TierBadge tier={result.risk_tier} /></div>
      </CardHeader>

      <CardContent className="space-y-4">
        <CriticalAlert indicators={result.critical_indicators} />

        <Tabs defaultValue="signals">
          <TabsList className="flex flex-wrap h-auto">
            <TabsTrigger value="signals">Signals</TabsTrigger>
            <TabsTrigger value="why">Why (SHAP)</TabsTrigger>
            <TabsTrigger value="report">Evidence</TabsTrigger>
            <TabsTrigger value="heatmap">Heatmap</TabsTrigger>
            <TabsTrigger value="entities">Entities</TabsTrigger>
          </TabsList>

          <TabsContent value="signals">
            <SignalsList signals={result.signals} />
          </TabsContent>

          <TabsContent value="why">
            <p className="mb-2 text-sm text-muted-foreground">
              How each forensic signal moved the XGBoost Trust Score:
            </p>
            <ShapChart contributions={result.shap_contributions} />
          </TabsContent>

          <TabsContent value="report">
            <div className="rounded-md bg-muted/50 p-4">
              <div className="mb-1 flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  AI Evidence Report
                </span>
                {result.llm_report_source && (
                  <Badge variant="secondary" className="text-[10px]">
                    {result.llm_report_source === "llm" ? "Llama 3.1 (local)" : "template"}
                  </Badge>
                )}
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {result.llm_evidence_report || result.evidence_summary}
              </p>
            </div>
          </TabsContent>

          <TabsContent value="heatmap">
            <PdfHeatmapViewer file={file} heatmapUrl={result.heatmap_url} />
          </TabsContent>

          <TabsContent value="entities">
            <EntitiesPanel entities={result.entities} />
            {result.extracted_text && (
              <>
                <Separator className="my-3" />
                <details>
                  <summary className="cursor-pointer text-xs uppercase tracking-wide text-muted-foreground">
                    Extracted Text ({result.text_extraction_method})
                  </summary>
                  <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-3 font-mono text-xs">
                    {result.extracted_text}
                  </pre>
                </details>
              </>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
