import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * Renders page 1 of a PDF with PDF.js onto a canvas, then overlays the ELA/
 * ManTraNet forgery heatmap (semi-transparent) precisely on top — spec §8
 * "PDF.js (with heatmap overlay)". For non-PDF uploads, falls back to showing
 * the heatmap image alone.
 */
export function PdfHeatmapViewer({
  file,
  heatmapUrl,
}: {
  file: File | null;
  heatmapUrl: string | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [overlay, setOverlay] = useState(true);
  const [rendered, setRendered] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      setErr(null);
      setRendered(false);
      if (!file || file.type !== "application/pdf") return;
      try {
        const buf = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
        const page = await pdf.getPage(1);
        const viewport = page.getViewport({ scale: 1.3 });
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;
        const ctx = canvas.getContext("2d")!;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: ctx, viewport }).promise;
        if (!cancelled) setRendered(true);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "PDF render failed");
      }
    }
    render();
    return () => {
      cancelled = true;
    };
  }, [file]);

  const isPdf = file?.type === "application/pdf";

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} />
          Heatmap overlay
        </label>
      </div>
      <div className="relative inline-block max-w-full overflow-auto rounded-md border bg-slate-900">
        {isPdf ? (
          <canvas ref={canvasRef} className="block max-w-full" />
        ) : (
          heatmapUrl && <img src={heatmapUrl} alt="document" className="block max-w-full opacity-90" />
        )}
        {overlay && heatmapUrl && (isPdf ? rendered : true) && (
          <img
            src={heatmapUrl}
            alt="forensic heatmap"
            className="pointer-events-none absolute inset-0 h-full w-full object-fill mix-blend-screen opacity-60"
          />
        )}
      </div>
      {err && <p className="mt-2 text-xs text-red-600">PDF preview: {err}</p>}
      <p className="mt-1.5 text-xs text-muted-foreground">
        Brighter regions = elevated re-compression / forgery probability.
      </p>
    </div>
  );
}
