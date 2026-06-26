"""TrustLens NER microservice.

Isolated so en_core_web_trf (which pins transformers<4.37) cannot conflict with
the main stack's LayoutLMv3 (transformers 4.46) and Sentence-Transformers.
See the trustlens-ner-microservice memory for the rationale.

Exposes POST /ner {text} -> {persons, orgs, locations, dates, money}.
The main backend does structured-ID extraction (PAN/GSTIN/Aadhaar/etc.) with
regex locally; this service only contributes contextual NER (names/orgs/places).
"""

from __future__ import annotations

import logging
import os

import spacy
from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="TrustLens NER", version="1.0.0")

_nlp = None

# A custom-trained spaCy model is used when present at this path; otherwise the
# stock en_core_web_trf serves. Override with NER_MODEL_PATH; revert to stock by
# removing the directory or setting NER_MODEL_PATH to a non-existent path.
NER_MODEL_PATH = os.environ.get("NER_MODEL_PATH", "/data/models/spacy-ner-prod")
STOCK_MODEL = "en_core_web_trf"


def get_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp
    if NER_MODEL_PATH and os.path.isdir(NER_MODEL_PATH):
        try:
            _nlp = spacy.load(NER_MODEL_PATH)
            logger.info("NER: loaded custom model from %s", NER_MODEL_PATH)
            return _nlp
        except Exception as e:  # corrupt/incompatible model -> never take prod down
            logger.warning("NER: custom model load failed (%s) — using %s.",
                           e.__class__.__name__, STOCK_MODEL)
    _nlp = spacy.load(STOCK_MODEL)
    logger.info("NER: loaded stock %s", STOCK_MODEL)
    return _nlp


class NerRequest(BaseModel):
    text: str


class NerResponse(BaseModel):
    persons: list[str]
    orgs: list[str]
    locations: list[str]
    dates: list[str]
    money: list[str]


def _dedup(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        k = it.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(it.strip())
    return out


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ner", response_model=NerResponse)
def ner(req: NerRequest) -> NerResponse:
    nlp = get_nlp()
    doc = nlp(req.text[:20000])  # cap to keep latency bounded
    buckets: dict[str, list[str]] = {"persons": [], "orgs": [], "locations": [], "dates": [], "money": []}
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            buckets["persons"].append(ent.text)
        elif ent.label_ == "ORG":
            buckets["orgs"].append(ent.text)
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            buckets["locations"].append(ent.text)
        elif ent.label_ == "DATE":
            buckets["dates"].append(ent.text)
        elif ent.label_ == "MONEY":
            buckets["money"].append(ent.text)
    return NerResponse(**{k: _dedup(v) for k, v in buckets.items()})
