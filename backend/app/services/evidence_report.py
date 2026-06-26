"""LLM evidence report generation (spec §3.2 LLM Insights).

LangChain + a local Ollama model (llama3.1:8b) turn the structured analysis
outputs into a plain-language underwriter report. Per spec the LLM uses
"prompt grounding guardrails" — it is instructed to describe ONLY the numbers
and flags we pass it, and not to invent facts.

If Ollama is unavailable or errors/times out, a deterministic template report
is returned instead (resilience — never blocks the pipeline).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
LLM_TIMEOUT = 60.0

SYSTEM_PROMPT = (
    "You are TrustLens, an assistant that writes concise, factual evidence reports "
    "for bank loan underwriters reviewing document authenticity. "
    "STRICT RULES: Use ONLY the structured findings provided in the user message. "
    "Do NOT invent facts, numbers, names, or document details that are not in the data. "
    "Do NOT give a final approve/reject decision — TrustLens augments the underwriter, "
    "who makes the final call. Write 3-5 short sentences in plain professional English. "
    "Explain the Trust Score, the risk tier, the top contributing signals, and any "
    "critical indicators. If a critical indicator is present, state it clearly."
)


def _build_facts(result: dict) -> str:
    lines = [
        f"Document: {result.get('filename')}",
        f"Classified as: {result.get('document_display_name')} "
        f"({result.get('document_category')})",
        f"Trust Score: {result.get('trust_score')}/100",
        f"Risk Tier: {result.get('risk_tier')} (routing: {result.get('routing')})",
        f"Scorer: {result.get('scorer')}",
    ]
    signals = result.get("signals", [])
    if signals:
        lines.append("Forensic signals (score out of 1.0):")
        for s in signals:
            lines.append(f"  - {s['name']}: {s['score']:.2f} — {s['detail']}")
    shap = result.get("shap_contributions") or {}
    if shap:
        ranked = sorted(shap.items(), key=lambda x: -abs(x[1]))[:4]
        lines.append("Top risk-score drivers (SHAP; + = toward fraud, - = toward clean):")
        for k, v in ranked:
            lines.append(f"  - {k}: {v:+.2f}")
    crit = result.get("critical_indicators") or []
    if crit:
        lines.append("CRITICAL forgery indicators: " + "; ".join(crit))
    return "\n".join(lines)


def _template_report(result: dict) -> str:
    tier = result.get("risk_tier")
    score = result.get("trust_score")
    name = result.get("document_display_name") or "document"
    routing = (result.get("routing") or "").replace("_", " ")
    crit = result.get("critical_indicators") or []
    parts = [
        f"This {name} received a Trust Score of {score}/100, placing it in the {tier} tier "
        f"({routing})."
    ]
    signals = sorted(result.get("signals", []), key=lambda s: s["score"])[:2]
    if signals:
        parts.append(
            "Lowest-scoring checks: "
            + "; ".join(f"{s['name']} ({s['score']:.2f}) — {s['detail']}" for s in signals)
            + "."
        )
    if crit:
        parts.append("Critical indicators detected: " + "; ".join(crit) + ".")
    parts.append("The underwriter should review the flagged evidence and make the final decision.")
    return " ".join(parts)


def generate_evidence_report(result: dict) -> tuple[str, str]:
    """Return (report_text, source) where source is 'llm' or 'template'."""
    facts = _build_facts(result)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_ollama import ChatOllama

        llm = ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.1,
            num_predict=300,
            client_kwargs={"timeout": LLM_TIMEOUT},
        )
        msg = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content="Structured findings:\n" + facts),
        ])
        text = (msg.content or "").strip()
        if len(text) >= 40:
            return text, "llm"
        logger.warning("LLM returned too-short report; using template.")
    except Exception as e:
        logger.warning("Ollama evidence report failed (%s) — using template.", e.__class__.__name__)
    return _template_report(result), "template"
