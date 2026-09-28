"""
app/services/retriever_service.py
───────────────────────────────────
Hybrid retrieval pipeline: vector + keyword → RRF merge → rerank.

Pipeline:
  1. Vector search   (FastEmbed cosine similarity via pgvector)
  2. Keyword search  (PostgreSQL full-text tsvector/tsquery)
  3. RRF merge       (Reciprocal Rank Fusion — combines both result lists)
  4. Cross-encoder rerank (ms-marco-MiniLM-L-6-v2) — optional via settings
  5. Return top_k

Settings (.env):
  RETRIEVAL_TOP_K          = 5
  RETRIEVAL_MIN_SIMILARITY = 0.25
  RETRIEVAL_RERANK         = false
  RETRIEVAL_HYBRID         = true
"""
from __future__ import annotations

import re
from typing import List
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
from pydantic import Field

from app.services.database import chunks_search, chunks_hybrid_search
from app.utils.logger import get_logger
from config.settings import settings

log = get_logger(__name__)

# ── Embedding model ───────────────────────────────────────────────────────

_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from fastembed import TextEmbedding
        log.info(f"Loading FastEmbed: {settings.fastembed_model}")
        _embed_model = TextEmbedding(model_name=settings.fastembed_model)
        log.info("FastEmbed ready")
    return _embed_model


def embed_query(text: str) -> List[float]:
    model = _get_embed_model()
    return list(model.embed([text]))[0].tolist()


# ── Reranker ──────────────────────────────────────────────────────────────

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            log.info("Loading cross-encoder reranker: ms-marco-MiniLM-L-6-v2")
            _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            log.info("Reranker ready")
        except ImportError:
            log.warning("sentence-transformers not installed — reranking disabled")
    return _reranker


def rerank(query: str, chunks: List[dict], top_k: int) -> List[dict]:
    """
    Cross-encoder reranking.
    Scores each (query, chunk) pair and returns top_k highest-scoring chunks.
    Falls back to RRF order if reranker unavailable.
    """
    reranker = _get_reranker()
    if reranker is None or len(chunks) <= top_k:
        return chunks[:top_k]

    pairs  = [(query, c["content"]) for c in chunks]
    scores = reranker.predict(pairs)

    for chunk, score in zip(chunks, scores):
        chunk["rerank_score"] = float(score)

    reranked = sorted(chunks, key=lambda x: x.get("rerank_score", 0), reverse=True)
    log.info(f"Reranked {len(chunks)} → top {top_k} chunks")
    for i, c in enumerate(reranked[:top_k]):
        log.debug(
            f"  [{i+1}] rerank={c['rerank_score']:.3f} "
            f"rrf={c.get('rrf_score', 0):.4f} "
            f"sim={c.get('similarity', 0):.3f} "
            f"{c['url'][:60]}"
        )
    return reranked[:top_k]


# ── Clean text ────────────────────────────────────────────────────────────

# def _clean(text: str) -> str:
#     """Strip citation artefacts like 【3†L1-L7】."""
#     text = re.sub(r"[\u3010\u3011\[][\d\w\u2020†:,\-]+[\u3011\u3010\]]", "", text)
#     text = re.sub(r"\u2020[\w\-:]+", "", text)
#     return re.sub(r" {2,}", " ", text).strip()

def _clean(text: str) -> str:
    """Strip citation artefacts like 【3†L1-L7】 and 【source 2】."""
    text = re.sub(r"【[^】]*】", "", text)          # removes 【anything】
    text = re.sub(r"\[[^\]]*\]", "", text)          # removes [anything]
    text = re.sub(r"\u2020[\w\-:]+", "", text)      # removes †markers
    return re.sub(r" {2,}", " ", text).strip()


# ── Core retrieve function ────────────────────────────────────────────────

def retrieve(
    query: str,
    top_k: int = None,
    initial_k: int = None,
    min_similarity: float = None,
    rerank_results: bool = None,   # None → reads from settings.retrieval_rerank
    hybrid: bool = None,           # None → reads from settings.retrieval_hybrid
) -> List[dict]:
    """
    Full hybrid retrieval pipeline:
      embed → vector + keyword search → RRF merge → rerank → top_k

    Args:
        query          : user query string
        top_k          : final chunks to return (default from settings)
        initial_k      : candidates before reranking (default top_k * 3)
        min_similarity : minimum cosine score (default from settings)
        rerank_results : apply cross-encoder reranking (default from settings)
        hybrid         : use hybrid search vector+keyword (default from settings)

    Returns list of chunk dicts:
      { chunk_id, page_id, content, url, title,
        similarity, rrf_score, rerank_score, metadata }
    """
    top_k          = top_k or settings.retrieval_top_k
    min_sim        = min_similarity if min_similarity is not None \
                     else settings.retrieval_min_similarity
    initial_k      = initial_k or min(top_k * 3, 20)

    # Read rerank and hybrid from settings if not explicitly passed
    rerank_results = rerank_results if rerank_results is not None \
                     else settings.retrieval_rerank
    hybrid         = hybrid if hybrid is not None \
                     else settings.retrieval_hybrid

    log.info(
        f"Retrieving: '{query[:80]}' "
        f"top_k={top_k} initial_k={initial_k} "
        f"hybrid={hybrid} rerank={rerank_results}"
    )

    # Step 1 — embed query
    query_vec = embed_query(query)

    # Step 2 — hybrid or vector-only search
    if hybrid:
        raw_chunks = chunks_hybrid_search(
            query_vec=query_vec,
            query_text=query,
            top_k=initial_k,
            min_similarity=min_sim,
        )
        log.info(f"Hybrid search returned {len(raw_chunks)} candidates (vector + keyword RRF)")
    else:
        raw_chunks = chunks_search(
            query_vec, top_k=initial_k, min_similarity=min_sim
        )
        log.info(f"Vector search returned {len(raw_chunks)} candidates")

    if not raw_chunks:
        log.warning("No chunks found — try a different query")
        return []

    # Step 3 — clean content
    for c in raw_chunks:
        c["content"]    = _clean(c["content"])
        c["similarity"] = round(float(c.get("similarity", 0)), 4)

    # Step 4 — rerank
    if rerank_results and len(raw_chunks) > top_k:
        final = rerank(query, raw_chunks, top_k)
    else:
        final = raw_chunks[:top_k]

    return final


# ── LangChain BaseRetriever wrapper ───────────────────────────────────────

class PgVectorRetriever(BaseRetriever):
    """
    LangChain-compatible hybrid retriever.
    Uses vector + keyword search with RRF merging.
    Reranking optional — controlled via settings.
    """
    top_k:          int   = Field(default_factory=lambda: settings.retrieval_top_k)
    min_similarity: float = Field(default_factory=lambda: settings.retrieval_min_similarity)
    rerank:         bool  = Field(default_factory=lambda: settings.retrieval_rerank)
    hybrid:         bool  = Field(default_factory=lambda: settings.retrieval_hybrid)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun = None,
    ) -> List[Document]:
        chunks = retrieve(
            query=query,
            top_k=self.top_k,
            min_similarity=self.min_similarity,
            rerank_results=self.rerank,
            hybrid=self.hybrid,
        )
        return [
            Document(
                page_content=c["content"],
                metadata={
                    "url":          c.get("url", ""),
                    "title":        c.get("title", ""),
                    "similarity":   c.get("similarity", 0),
                    "rrf_score":    c.get("rrf_score", 0),
                    "rerank_score": c.get("rerank_score", None),
                    "chunk_id":     c.get("chunk_id"),
                    "page_id":      c.get("page_id"),
                },
            )
            for c in chunks
        ]