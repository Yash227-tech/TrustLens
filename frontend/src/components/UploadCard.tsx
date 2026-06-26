import { useRef, useState } from "react";
import { UploadCloud, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { analyzeDocument } from "@/lib/api";
import type { AnalyzeResponse } from "@/types";

const ACCEPT =
  "application/pdf,image/png,image/jpeg,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function UploadCard({ onResult }: { onResult: (r: AnalyzeResponse) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handle(file: File) {
    setError(null);
    setFilename(file.name);
    setStatus("queued");
    try {
      const result = await analyzeDocument(file, setStatus);
      onResult(result);
      setStatus(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setStatus(null);
    }
  }

  const busy = status !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload Document</CardTitle>
        <CardDescription>PDF, DOCX, PNG or JPEG — bank statements, ITRs, salary slips, KYC, legal docs.</CardDescription>
      </CardHeader>
      <CardContent>
        <div
          className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-10 text-center transition ${
            busy ? "border-muted bg-muted/40" : "cursor-pointer border-input hover:border-primary/50 hover:bg-accent/40"
          }`}
          onClick={() => !busy && inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (!busy && e.dataTransfer.files?.[0]) handle(e.dataTransfer.files[0]);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handle(e.target.files[0])}
          />
          {busy ? (
            <>
              <Loader2 className="mb-3 h-8 w-8 animate-spin text-primary" />
              <p className="font-medium capitalize">{status}: {filename}</p>
              <p className="mt-1 text-xs text-muted-foreground">Queued to Celery · GPU forensics running</p>
            </>
          ) : (
            <>
              <UploadCloud className="mb-3 h-8 w-8 text-muted-foreground" />
              <p className="font-medium">Click or drag a document here</p>
              <p className="mt-1 text-xs text-muted-foreground">7 forensic checks · cross-source verify · &lt; 30s</p>
            </>
          )}
        </div>
        {error && <p className="mt-3 text-sm text-red-600">Error: {error}</p>}
      </CardContent>
    </Card>
  );
}
