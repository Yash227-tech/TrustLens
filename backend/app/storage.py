"""MinIO / S3 object storage (spec §8 "MinIO/S3 object storage").

Uploads and ELA/ManTraNet heatmaps are persisted to MinIO buckets as the object
store of record. The local /data bind-mount stays as a working cache so the
worker's file access and the demo keep running even if MinIO is unavailable —
the client degrades to a no-op (best-effort) rather than breaking the pipeline.
"""

from __future__ import annotations

import io
import logging
import os
import threading

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "trustlens")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "trustlens_dev")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"

UPLOAD_BUCKET = "trustlens-uploads"
HEATMAP_BUCKET = "trustlens-heatmaps"
_BUCKETS = (UPLOAD_BUCKET, HEATMAP_BUCKET)

_client = None
_lock = threading.Lock()
_unavailable = False


def _get_client():
    global _client, _unavailable
    if _client is not None:
        return _client
    if _unavailable:
        return None
    with _lock:
        if _client is not None:
            return _client
        try:
            from minio import Minio
            c = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY,
                      secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)
            for b in _BUCKETS:
                if not c.bucket_exists(b):
                    c.make_bucket(b)
            _client = c
            logger.info("MinIO object storage ready at %s", MINIO_ENDPOINT)
            return _client
        except Exception as e:
            logger.warning("MinIO unavailable (%s) — using /data bind-mount only.",
                           e.__class__.__name__)
            _unavailable = True
            return None


def put_object(bucket: str, key: str, data: bytes, content_type: str) -> bool:
    """Persist bytes to MinIO. Best-effort: returns False (no-op) if MinIO is down."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.put_object(bucket, key, io.BytesIO(data), length=len(data),
                          content_type=content_type)
        return True
    except Exception as e:
        logger.warning("MinIO put_object %s/%s failed: %s", bucket, key, e.__class__.__name__)
        return False


def get_object(bucket: str, key: str) -> bytes | None:
    """Fetch bytes from MinIO, or None if unavailable/not found."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.get_object(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    except Exception:
        return None
