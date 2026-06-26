from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.storage import HEATMAP_BUCKET, get_object

router = APIRouter(prefix="/api", tags=["heatmap"])

HEATMAP_DIR = Path("/data/heatmaps")


@router.get("/heatmap/{document_id}.png")
def get_heatmap(document_id: str):
    safe_id = "".join(c for c in document_id if c.isalnum() or c == "-")
    path = HEATMAP_DIR / f"{safe_id}.png"
    if path.exists():  # disk cache (fast path)
        return FileResponse(path, media_type="image/png")
    data = get_object(HEATMAP_BUCKET, f"{safe_id}.png")  # MinIO store of record
    if data is not None:
        return Response(content=data, media_type="image/png")
    raise HTTPException(status_code=404, detail="Heatmap not found")
