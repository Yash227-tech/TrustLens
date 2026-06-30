"""Cross-document consistency analysis (spec §6 NLP Cross-Doc Check).

Given the extracted entities of every document in a case, checks that the same
applicant identity is consistent across all documents:

  - Hard IDs (PAN, GSTIN, Aadhaar, IFSC): must match exactly across docs. A
    second distinct value is a critical fraud indicator.
  - Names: matched with phonetic + fuzzy matching (spec §6 — "phonetic + fuzzy
    matching for Indian names") to tolerate OCR noise, initials, and spelling
    variants. Genuinely different names across docs are flagged for review.

Returns {consistency_score, passed, critical, findings}.
"""

from __future__ import annotations

import logging
import threading

import jellyfish
from rapidfuzz import fuzz

from app.forensics.face_match import compare_faces

logger = logging.getLogger(__name__)

HARD_ID_FIELDS = ["pan", "gstin", "aadhaar", "ifsc", "passport"]

# Documents whose PURPOSE is to establish the applicant's identity. When a case
# carries 2+ of these, we must be able to CONFIRM they belong to the same person.
# If an identity document yields no readable identity (no name AND no hard ID), or
# the names across them don't match, we cannot fast-track it — it goes to human
# review (YELLOW). A bank statement / salary slip is NOT an identity document, so
# it not carrying a name never triggers this (avoids over-flagging genuine cases).
IDENTITY_DOC_TYPES = {"pan", "aadhaar", "passport", "voter_id", "driving_license"}

NAME_FUZZY_THRESHOLD = 82      # rapidfuzz token_sort_ratio >= this => same name
NAME_PHONETIC_BONUS = True     # also accept if metaphone codes match

# Sentence-Transformers semantic matching (spec §3.2 "spaCy + Sentence-Transformers").
# Complements fuzzy+phonetic: embedding cosine similarity catches transliteration /
# word-order variants of Indian names those miss. CONSERVATIVE threshold — for
# identity matching, over-matching would HIDE a real name mismatch (bank-unsafe),
# so this only ADDS matches at high confidence; it never loosens below fuzzy.
_ST_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SEMANTIC_THRESHOLD = 0.82
_st_model = None
_st_lock = threading.Lock()
_st_unavailable = False


def _get_st_model():
    global _st_model, _st_unavailable
    if _st_model is not None:
        return _st_model
    if _st_unavailable:
        return None
    with _st_lock:
        if _st_model is not None:
            return _st_model
        try:
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer(_ST_MODEL_NAME)
            logger.info("Sentence-Transformers loaded for cross-doc semantic matching.")
            return _st_model
        except Exception as e:
            logger.warning("Sentence-Transformers unavailable (%s) — fuzzy+phonetic only.",
                           e.__class__.__name__)
            _st_unavailable = True
            return None


def _semantic_match(a: str, b: str) -> bool:
    model = _get_st_model()
    if model is None:
        return False
    try:
        from sentence_transformers import util
        emb = model.encode([a, b], convert_to_tensor=True, normalize_embeddings=True)
        return float(util.cos_sim(emb[0], emb[1])) >= SEMANTIC_THRESHOLD
    except Exception:
        return False


def _names_match(a: str, b: str) -> bool:
    a1, b1 = a.strip().lower(), b.strip().lower()
    if not a1 or not b1:
        return False
    if fuzz.token_sort_ratio(a1, b1) >= NAME_FUZZY_THRESHOLD:
        return True
    if NAME_PHONETIC_BONUS:
        try:
            if jellyfish.metaphone(a1) == jellyfish.metaphone(b1) and jellyfish.metaphone(a1):
                return True
        except Exception:
            pass
    return _semantic_match(a1, b1)  # last resort, high-confidence only


def _doc_label(doc: dict) -> str:
    return doc.get("filename") or doc.get("document_type") or doc.get("id", "doc")


def analyze_case_consistency(documents: list[dict]) -> dict:
    """documents: list of {filename, document_type, entities: {...}}."""
    findings: list[dict] = []
    score = 1.0
    critical = False
    review_required = False  # cannot CONFIRM same applicant -> human review (YELLOW)

    docs = [d for d in documents if d.get("entities")]
    if len(docs) < 2:
        return {
            "consistency_score": 1.0,
            "passed": True,
            "critical": False,
            "findings": [],
            "note": "Need at least 2 analysed documents to cross-check.",
        }

    # --- Hard IDs: exact match required ---
    for field in HARD_ID_FIELDS:
        # map value -> list of doc labels that contain it
        value_docs: dict[str, list[str]] = {}
        for d in docs:
            for v in d["entities"].get(field, []):
                value_docs.setdefault(v, []).append(_doc_label(d))
        distinct = list(value_docs.keys())
        if len(distinct) > 1:
            critical = True
            score -= 0.40
            findings.append({
                "field": field.upper(),
                "severity": "critical",
                "detail": f"Conflicting {field.upper()} values across documents: "
                          + "; ".join(f"{v} ({', '.join(docs_)})" for v, docs_ in value_docs.items()),
            })
        elif len(distinct) == 1 and len(value_docs[distinct[0]]) >= 2:
            findings.append({
                "field": field.upper(),
                "severity": "ok",
                "detail": f"{field.upper()} {distinct[0]} consistent across "
                          f"{len(value_docs[distinct[0]])} documents.",
            })

    # --- Names: phonetic + fuzzy clustering ---
    name_doc_pairs: list[tuple[str, str]] = []
    for d in docs:
        for nm in d["entities"].get("person", []):
            name_doc_pairs.append((nm, _doc_label(d)))

    if name_doc_pairs:
        # Greedy cluster by match
        clusters: list[list[tuple[str, str]]] = []
        for nm, lbl in name_doc_pairs:
            placed = False
            for cl in clusters:
                if _names_match(nm, cl[0][0]):
                    cl.append((nm, lbl))
                    placed = True
                    break
            if not placed:
                clusters.append([(nm, lbl)])
        # A cluster "covers" a document if it holds a name from it. The applicant
        # is consistent iff ONE cluster covers every document that carried a name —
        # i.e. a single name appears on all of them. Secondary names (father /
        # spouse on an ID, stray OCR fragments) form their own clusters and are
        # ignored, so a PAN's father-name does NOT manufacture a false mismatch.
        # Only when NO cluster spans all named documents is there a genuine cross-
        # document name conflict -> escalate to review (YELLOW), never auto-RED
        # (OCR noise / married names / initials make a name string too ambiguous to
        # auto-reject; a conflicting HARD ID above is the deterministic RED case).
        clusters.sort(key=len, reverse=True)
        docs_with_names = {lbl for _, lbl in name_doc_pairs}
        shared = next(
            (cl for cl in clusters if {lbl for _, lbl in cl} >= docs_with_names), None)
        if shared is not None or len(docs_with_names) < 2:
            applicant = sorted(n for n, _ in (shared or clusters[0]))[0]
            findings.append({
                "field": "NAME",
                "severity": "ok",
                "detail": f"Applicant name consistent across documents ('{applicant}').",
            })
        else:
            primary = sorted(n for n, _ in clusters[0])[0]
            others = sorted({n for cl in clusters[1:] for n, _ in cl})[:4]
            review_required = True
            score -= 0.20
            findings.append({
                "field": "NAME",
                "severity": "warning",
                "detail": f"Names do not match across documents: primary='{primary}', "
                          f"also seen {others}. Escalate — verify identity manually.",
            })

    # --- Identity coverage: can we CONFIRM the same applicant? ---
    # Look at ALL documents (incl. those whose OCR produced nothing) so a totally
    # unreadable ID card is caught. Only enforced when the case has 2+ identity
    # documents — the situation where "are these the same person?" actually matters.
    id_docs = [d for d in documents if d.get("document_type") in IDENTITY_DOC_TYPES]
    if len(id_docs) >= 2:
        unreadable = []
        for d in id_docs:
            ent = d.get("entities") or {}
            has_name = bool(ent.get("person"))
            has_hard_id = any(ent.get(f) for f in HARD_ID_FIELDS)
            if not has_name and not has_hard_id:
                unreadable.append(_doc_label(d))
        if unreadable:
            review_required = True
            score = min(score, 0.6)
            findings.append({
                "field": "IDENTITY",
                "severity": "warning",
                "detail": f"Cannot confirm same applicant: no readable identity "
                          f"(name or ID number) on {', '.join(unreadable)}. "
                          f"Manual identity verification required.",
            })

    # --- Faces: cross-document photo match (photo-superimposition / mixed identity) ---
    # Per-doc face embeddings are produced by forensics/face_match for ID documents.
    # Two ID photos that don't match => a swapped photo or two people's IDs combined
    # -> review (YELLOW). Never auto-RED on its own: genuine same-person-different-
    # photo pairs (different ages, low-res, B&W) have real spread, so a human
    # verifies the portraits. A conflicting hard ID above is the deterministic RED.
    face_docs: list[tuple[str, list]] = []
    for d in documents:
        if d.get("document_type") not in IDENTITY_DOC_TYPES:
            continue
        face = d.get("face") or {}
        if face.get("quality") == "ok" and face.get("embedding"):
            face_docs.append((_doc_label(d), face["embedding"]))
    if len(face_docs) >= 2:
        mismatches, matches = [], []
        for i in range(len(face_docs)):
            for j in range(i + 1, len(face_docs)):
                (la, ea), (lb, eb) = face_docs[i], face_docs[j]
                cmp = compare_faces(ea, eb)
                if cmp["verdict"] == "mismatch":
                    mismatches.append((la, lb, cmp["similarity"]))
                elif cmp["verdict"] == "match":
                    matches.append((la, lb, cmp["similarity"]))
        if mismatches:
            review_required = True
            score -= 0.25
            la, lb, sim = min(mismatches, key=lambda m: m[2])
            findings.append({
                "field": "FACE",
                "severity": "warning",
                "detail": f"Face photos differ across identity documents ({la} vs {lb}, "
                          f"similarity {sim}). Possible photo substitution or mixed identity — "
                          f"verify the portraits manually.",
            })
        elif matches:
            la, lb, sim = max(matches, key=lambda m: m[2])
            findings.append({
                "field": "FACE",
                "severity": "ok",
                "detail": f"Face photos consistent across identity documents "
                          f"(e.g. {la} vs {lb}, similarity {sim}).",
            })

    score = max(0.0, min(1.0, score))
    # GREEN/"Consistent" only when identity is positively confirmed. A name
    # mismatch or unreadable identity flips this to the YELLOW "Review" state
    # (passed=False, not critical); a hard-ID conflict is critical (RED).
    passed = score >= 0.7 and not critical and not review_required

    return {
        "consistency_score": round(score, 3),
        "passed": passed,
        "critical": critical,
        "review_required": review_required,
        "findings": findings,
    }
