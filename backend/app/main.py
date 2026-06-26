import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import analyze, audit, auth, cases, health, heatmap

logger = logging.getLogger(__name__)

app = FastAPI(
    title="TrustLens API",
    description="AI-Assisted Underwriting Intelligence Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(heatmap.router)
app.include_router(cases.router)
app.include_router(audit.router)


@app.on_event("startup")
async def on_startup():
    try:
        await init_db()
        logger.info("Database initialised.")
    except Exception as e:
        logger.warning("DB init failed (cases endpoints will error until DB is ready): %s", e)


@app.get("/")
def root():
    return {"service": "TrustLens", "version": "0.1.0", "status": "running"}
