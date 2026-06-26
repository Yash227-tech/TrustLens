"""Celery application instance per spec §8 (Celery + Redis async task queue).

Workers and the FastAPI process both import this module, so it must be safe
to instantiate without any side effects beyond reading env vars. The actual
task definitions live in app.tasks (registered via `include`).
"""

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "trustlens",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=180,          # 3-min hard kill
    task_soft_time_limit=150,     # 2.5-min soft warning
    worker_prefetch_multiplier=1, # don't hoard tasks — keep GPU busy fairly
    result_expires=3600,          # results in Redis for 1 hour
)
