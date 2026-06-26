import { useState } from "react";
import { UploadCard } from "@/components/UploadCard";
import { ResultPanel } from "@/components/ResultPanel";
import { Card, CardContent } from "@/components/ui/card";
import type { AnalyzeResponse } from "@/types";

export function AnalyzePage() {
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-6">
        <UploadCardWrapper onResult={setResult} onFile={setFile} />
      </div>
      {result ? (
        <ResultPanel result={result} file={file} />
      ) : (
        <Card className="border-dashed">
          <CardContent className="flex h-full min-h-48 items-center justify-center p-10 text-center text-sm text-muted-foreground">
            Upload a document to see Trust Score, forensic signals, SHAP attribution,
            the AI evidence report, and the forgery heatmap.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// Wrap UploadCard to also capture the File (for the PDF.js viewer).
function UploadCardWrapper({
  onResult,
  onFile,
}: {
  onResult: (r: AnalyzeResponse) => void;
  onFile: (f: File) => void;
}) {
  return (
    <div
      onDropCapture={(e) => {
        const f = (e as unknown as DragEvent).dataTransfer?.files?.[0];
        if (f) onFile(f);
      }}
      onChangeCapture={(e) => {
        const f = (e.target as HTMLInputElement).files?.[0];
        if (f) onFile(f);
      }}
    >
      <UploadCard onResult={onResult} />
    </div>
  );
}
