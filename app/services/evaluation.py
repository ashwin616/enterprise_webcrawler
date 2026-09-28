"""
app/services/evaluation.py
───────────────────────────
RAG evaluation metrics.

Metrics:
  1. Faithfulness       — is the answer grounded in the retrieved context?
  2. Answer Relevance   — does the answer address the question?
  3. Context Recall     — do retrieved chunks contain the answer?
  4. Context Precision  — are retrieved chunks relevant to the query?
  5. BLEU score         — n-gram overlap vs reference answer
  6. ROUGE-L score      — longest common subsequence vs reference

Usage:
    from app.services.evaluation import evaluate_rag_response

    result = evaluate_rag_response(
        query="What is pgvector?",
        answer="pgvector is a PostgreSQL extension for vector similarity search.",
        chunks=[{"content": "...", "url": "..."}],
        reference_answer="optional ground-truth answer",
    )
    print(result)
"""
from __future__ import annotations

import re
from typing import List, Optional
from app.services.llm_service import get_llm
from app.utils.logger import get_logger

log = get_logger(__name__)


# ── LLM-based metrics ─────────────────────────────────────────────────────

def _llm_score(prompt: str) -> float:
    """Ask LLM to score 0–1 and parse the float."""
    try:
        llm = get_llm()
        response = llm.invoke(prompt)
        # Find first float/int in response
        match = re.search(r"\b(0(\.\d+)?|1(\.0+)?)\b", response)
        if match:
            return round(float(match.group()), 3)
        log.warning(f"Could not parse score from: {response[:100]}")
        return 0.0
    except Exception as e:
        log.error(f"LLM scoring failed: {e}")
        return 0.0


def faithfulness_score(query: str, answer: str, context: str) -> float:
    """
    Faithfulness: is every claim in the answer supported by the context?
    Score 0 (hallucinated) → 1 (fully grounded).
    """
    prompt = f"""You are an evaluator checking if an answer is faithful to the context.

Context:
{context[:3000]}

Question: {query}
Answer: {answer}

Score from 0.0 to 1.0:
- 1.0 = every claim in the answer is directly supported by the context
- 0.5 = partially supported
- 0.0 = answer contains claims not in the context (hallucination)

Reply with ONLY a number between 0.0 and 1.0."""
    score = _llm_score(prompt)
    log.debug(f"Faithfulness score: {score}")
    return score


def answer_relevance_score(query: str, answer: str) -> float:
    """
    Answer Relevance: does the answer actually address the question?
    Score 0 (irrelevant) → 1 (fully relevant).
    """
    prompt = f"""You are an evaluator checking if an answer is relevant to the question.

Question: {query}
Answer: {answer}

Score from 0.0 to 1.0:
- 1.0 = answer directly and completely addresses the question
- 0.5 = answer is partially relevant
- 0.0 = answer is off-topic or does not address the question

Reply with ONLY a number between 0.0 and 1.0."""
    score = _llm_score(prompt)
    log.debug(f"Answer relevance score: {score}")
    return score


def context_recall_score(query: str, context: str, reference: str) -> float:
    """
    Context Recall: does the retrieved context contain the information
    needed to answer the question?
    Requires a reference answer.
    Score 0 (missing) → 1 (fully covered).
    """
    if not reference:
        return -1.0   # -1 signals "not measured"
    prompt = f"""You are an evaluator checking if the context contains enough
information to answer the question, given the reference answer.

Question: {query}
Reference answer: {reference}
Retrieved context:
{context[:3000]}

Score from 0.0 to 1.0:
- 1.0 = context contains all information needed
- 0.5 = context partially covers the reference answer
- 0.0 = context is missing key information

Reply with ONLY a number between 0.0 and 1.0."""
    score = _llm_score(prompt)
    log.debug(f"Context recall score: {score}")
    return score


def context_precision_score(query: str, chunks: List[dict]) -> float:
    """
    Context Precision: what fraction of retrieved chunks are relevant?
    Uses similarity scores if available, otherwise asks LLM.
    """
    if not chunks:
        return 0.0

    # If similarity scores available, use them directly
    if all("similarity" in c for c in chunks):
        avg_sim = sum(c["similarity"] for c in chunks) / len(chunks)
        log.debug(f"Context precision (avg similarity): {avg_sim:.3f}")
        return round(avg_sim, 3)

    # Fallback: LLM scoring
    context_preview = "\n---\n".join(
        c["content"][:300] for c in chunks[:5]
    )
    prompt = f"""You are an evaluator checking if retrieved chunks are relevant to the query.

Query: {query}
Retrieved chunks:
{context_preview}

What fraction of these chunks are relevant to the query?
Reply with ONLY a number between 0.0 and 1.0."""
    return _llm_score(prompt)


# ── Statistical metrics ───────────────────────────────────────────────────

def bleu_score(hypothesis: str, reference: str) -> float:
    """
    BLEU score — n-gram precision overlap between answer and reference.
    Returns 0–1. Requires reference answer.
    """
    if not reference:
        return -1.0
    try:
        from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
        import nltk
        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            nltk.download("punkt", quiet=True)

        ref_tokens  = reference.lower().split()
        hyp_tokens  = hypothesis.lower().split()
        smoother    = SmoothingFunction().method1
        score       = sentence_bleu([ref_tokens], hyp_tokens,
                                    smoothing_function=smoother)
        return round(score, 4)
    except ImportError:
        log.warning("nltk not installed — BLEU score unavailable")
        return -1.0
    except Exception as e:
        log.error(f"BLEU error: {e}")
        return -1.0


def rouge_l_score(hypothesis: str, reference: str) -> float:
    """
    ROUGE-L score — longest common subsequence F1.
    Returns 0–1. Requires reference answer.
    """
    if not reference:
        return -1.0
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        scores = scorer.score(reference, hypothesis)
        return round(scores["rougeL"].fmeasure, 4)
    except ImportError:
        log.warning("rouge_score not installed — ROUGE-L unavailable")
        return _rouge_l_fallback(hypothesis, reference)


def _rouge_l_fallback(hyp: str, ref: str) -> float:
    """Pure-Python LCS-based ROUGE-L (no external dependency)."""
    h, r = hyp.lower().split(), ref.lower().split()
    m, n = len(h), len(r)
    if m == 0 or n == 0:
        return 0.0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = dp[i-1][j-1] + 1 if h[i-1] == r[j-1] else max(dp[i-1][j], dp[i][j-1])
    lcs = dp[m][n]
    precision = lcs / m if m else 0
    recall    = lcs / n if n else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    return round(f1, 4)


# ── Full evaluation ───────────────────────────────────────────────────────

def evaluate_rag_response(
    query:            str,
    answer:           str,
    chunks:           List[dict],
    reference_answer: Optional[str] = None,
) -> dict:
    """
    Run all evaluation metrics for a RAG response.

    Args:
        query            : the user's question
        answer           : the LLM's answer
        chunks           : retrieved chunks (list of dicts with 'content', 'url', etc.)
        reference_answer : optional ground-truth answer for BLEU/ROUGE/recall

    Returns:
        {
          "faithfulness":       0.0–1.0,
          "answer_relevance":   0.0–1.0,
          "context_precision":  0.0–1.0,
          "context_recall":     0.0–1.0 or -1 if no reference,
          "bleu":               0.0–1.0 or -1 if no reference,
          "rouge_l":            0.0–1.0 or -1 if no reference,
          "overall_score":      weighted average of available scores,
          "chunks_used":        int,
          "has_reference":      bool,
        }
    """
    log.info(f"Evaluating RAG response for query: '{query[:60]}'")

    context = "\n---\n".join(c["content"] for c in chunks[:5])

    # Core metrics (always computed)
    faith   = faithfulness_score(query, answer, context)
    rel     = answer_relevance_score(query, answer)
    prec    = context_precision_score(query, chunks)

    # Reference-dependent metrics
    recall  = context_recall_score(query, context, reference_answer)
    bleu    = bleu_score(answer, reference_answer)
    rouge   = rouge_l_score(answer, reference_answer)

    # Weighted overall score (only available metrics)
    core_scores = [faith, rel, prec]
    weights     = [0.4, 0.35, 0.25]
    overall     = round(sum(s * w for s, w in zip(core_scores, weights)), 3)

    result = {
        "faithfulness":      faith,
        "answer_relevance":  rel,
        "context_precision": prec,
        "context_recall":    recall,
        "bleu":              bleu,
        "rouge_l":           rouge,
        "overall_score":     overall,
        "chunks_used":       len(chunks),
        "has_reference":     bool(reference_answer),
    }

    log.info(
        f"Evaluation: faithfulness={faith} relevance={rel} "
        f"precision={prec} overall={overall}"
    )
    return result
