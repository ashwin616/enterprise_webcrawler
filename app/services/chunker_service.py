# """
# app/services/chunker_service.py
# ────────────────────────────────
# LangChain-based text chunking.

# Strategies:
#   recursive  — LangChain RecursiveCharacterTextSplitter (default, best for most text)
#   token      — LangChain TokenTextSplitter (tiktoken cl100k_base)
#   sentence   — regex sentence splitting with overlap

# Config is driven by .env:
#   CHUNK_STRATEGY, CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_MIN_SIZE
# """
# from __future__ import annotations

# import re
# from typing import List
# from langchain_text_splitters import (
#     RecursiveCharacterTextSplitter,
#     TokenTextSplitter,
# )
# from config.settings import settings
# from app.utils.logger import get_logger

# log = get_logger(__name__)


# def chunk_text(text: str, metadata: dict = None) -> List[dict]:
#     """
#     Split text into chunks using strategy from settings.

#     Returns list of dicts:
#       { chunk_index, content, token_count, char_count, metadata }
#     """
#     if not text or not text.strip():
#         return []

#     strategy = settings.chunk_strategy
#     log.debug(f"Chunking {len(text)} chars — strategy={strategy} "
#               f"size={settings.chunk_size} overlap={settings.chunk_overlap}")

#     if strategy == "recursive":
#         raw_chunks = _recursive_split(text)
#     elif strategy == "token":
#         raw_chunks = _token_split(text)
#     elif strategy == "sentence":
#         raw_chunks = _sentence_split(text)
#     else:
#         log.warning(f"Unknown strategy '{strategy}' — using recursive")
#         raw_chunks = _recursive_split(text)

#     result = []
#     for i, chunk in enumerate(raw_chunks):
#         chunk = chunk.strip()
#         if len(chunk) < settings.chunk_min_size:
#             continue
#         result.append({
#             "chunk_index": i,
#             "content":     chunk,
#             "token_count": _approx_tokens(chunk),
#             "char_count":  len(chunk),
#             "metadata":    metadata or {},
#         })

#     log.info(f"Chunking → {len(result)} chunks "
#              f"(avg {sum(c['char_count'] for c in result) // max(len(result),1)} chars each)")
#     return result


# # ── Strategies ────────────────────────────────────────────────────────────

# def _recursive_split(text: str) -> List[str]:
#     """
#     LangChain RecursiveCharacterTextSplitter.
#     Splits on paragraphs → sentences → words → chars.
#     Best general-purpose splitter.
#     """
#     splitter = RecursiveCharacterTextSplitter(
#         chunk_size=settings.chunk_size * 4,      # chars (approx 1 token = 4 chars)
#         chunk_overlap=settings.chunk_overlap * 4,
#         length_function=len,
#         separators=["\n\n", "\n", ". ", " ", ""],
#     )
#     return splitter.split_text(text)


# def _token_split(text: str) -> List[str]:
#     """
#     LangChain TokenTextSplitter using tiktoken cl100k_base.
#     Splits on exact token counts.
#     """
#     splitter = TokenTextSplitter(
#         chunk_size=settings.chunk_size,
#         chunk_overlap=settings.chunk_overlap,
#         encoding_name="cl100k_base",
#     )
#     return splitter.split_text(text)


# def _sentence_split(text: str) -> List[str]:
#     """Sentence-aware splitting with overlap."""
#     sentences = re.split(r"(?<=[.!?])\s+", text)
#     chunks, current, current_len = [], [], 0
#     for sent in sentences:
#         sent_len = _approx_tokens(sent)
#         if current_len + sent_len > settings.chunk_size and current:
#             chunks.append(" ".join(current))
#             overlap, overlap_len = [], 0
#             for s in reversed(current):
#                 sl = _approx_tokens(s)
#                 if overlap_len + sl <= settings.chunk_overlap:
#                     overlap.insert(0, s)
#                     overlap_len += sl
#                 else:
#                     break
#             current, current_len = overlap, overlap_len
#         current.append(sent)
#         current_len += sent_len
#     if current:
#         chunks.append(" ".join(current))
#     return chunks


# def _approx_tokens(text: str) -> int:
#     return max(1, len(text) // 4)

"""
app/services/chunker_service.py
────────────────────────────────
LangChain-based text chunking.

Strategies:
  semantic   — SemanticChunker using FastEmbed embeddings (splits on meaning boundaries)
  recursive  — LangChain RecursiveCharacterTextSplitter
  token      — LangChain TokenTextSplitter (tiktoken cl100k_base)
  sentence   — regex sentence splitting with overlap

Config is driven by .env:
  CHUNK_STRATEGY=semantic   ← change this to switch strategy
  CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_MIN_SIZE
"""
from __future__ import annotations

import re
from typing import List
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)
from config.settings import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


def chunk_text(text: str, metadata: dict = None) -> List[dict]:
    """
    Split text into chunks using strategy from settings.

    Returns list of dicts:
      { chunk_index, content, token_count, char_count, metadata }
    """
    if not text or not text.strip():
        return []

    strategy = settings.chunk_strategy
    log.debug(f"Chunking {len(text)} chars — strategy={strategy} "
              f"size={settings.chunk_size} overlap={settings.chunk_overlap}")

    if strategy == "semantic":
        raw_chunks = _semantic_split(text)
    elif strategy == "recursive":
        raw_chunks = _recursive_split(text)
    elif strategy == "token":
        raw_chunks = _token_split(text)
    elif strategy == "sentence":
        raw_chunks = _sentence_split(text)
    else:
        log.warning(f"Unknown strategy '{strategy}' — falling back to semantic")
        raw_chunks = _semantic_split(text)

    result = []
    for i, chunk in enumerate(raw_chunks):
        chunk = chunk.strip()
        if len(chunk) < settings.chunk_min_size:
            continue
        result.append({
            "chunk_index": i,
            "content":     chunk,
            "token_count": _approx_tokens(chunk),
            "char_count":  len(chunk),
            "metadata":    metadata or {},
        })

    log.info(f"Chunking → {len(result)} chunks "
             f"(avg {sum(c['char_count'] for c in result) // max(len(result),1)} chars each)")
    return result


# ── Strategies ────────────────────────────────────────────────────────────

# def _semantic_split(text: str) -> List[str]:
#     """
#     SemanticChunker — splits on meaning boundaries using FastEmbed embeddings.

#     How it works:
#       1. Splits text into sentences
#       2. Embeds each sentence using the same FastEmbed model used for storage
#       3. Calculates cosine similarity between consecutive sentences
#       4. Splits when similarity drops below the percentile threshold
#          (topic change detected)

#     Result: chunks that contain topically coherent content — much better
#     for RAG retrieval than fixed-size splitting.

#     Requires: pip install langchain-experimental
#     """
#     try:
#         from langchain_experimental.text_splitter import SemanticChunker
#         from langchain_community.embeddings import FastEmbedEmbeddings

#         embeddings = FastEmbedEmbeddings(model_name=settings.fastembed_model)
#         splitter = SemanticChunker(
#             embeddings=embeddings,
#             breakpoint_threshold_type="percentile",
#             breakpoint_threshold_amount=95,   # split when similarity drops below 95th percentile
#         )
#         chunks = splitter.split_text(text)
#         log.debug(f"  Semantic split produced {len(chunks)} chunks")
#         return chunks

#     except ImportError:
#         log.warning(
#             "langchain-experimental not installed — falling back to recursive. "
#             "Run: pip install langchain-experimental"
#         )
#         return _recursive_split(text)
#     except Exception as e:
#         log.warning(f"Semantic split failed ({e}) — falling back to recursive")
#         return _recursive_split(text)

def _semantic_split(text: str) -> List[str]:
    """
    Custom semantic chunker using FastEmbed — no extra dependencies needed.

    How it works:
      1. Splits text into sentences
      2. Embeds each sentence using FastEmbed (same model used for storage)
      3. Calculates cosine similarity between consecutive sentences
      4. Splits when similarity drops below threshold (topic change detected)

    Result: chunks that contain topically coherent content — much better
    for RAG retrieval than fixed-size splitting.
    """
    import numpy as np
    from fastembed import TextEmbedding

    # Step 1 — split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        return sentences if sentences else [text]

    # Step 2 — embed all sentences using same model as storage
    model      = TextEmbedding(model_name=settings.fastembed_model)
    embeddings = list(model.embed(sentences))

    # Step 3 — cosine similarity between consecutive sentence pairs
    def cosine_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))

    similarities = [
        cosine_sim(embeddings[i], embeddings[i + 1])
        for i in range(len(embeddings) - 1)
    ]

    # Step 4 — split where similarity is in bottom 25% (topic boundary)
    threshold  = float(np.percentile(similarities, 25))
    split_idxs = [i + 1 for i, s in enumerate(similarities) if s < threshold]

    # Step 5 — group sentences into chunks at split points
    chunks, start = [], 0
    for idx in split_idxs:
        chunk = " ".join(sentences[start:idx]).strip()
        if chunk:
            chunks.append(chunk)
        start = idx

    # Add final chunk
    last = " ".join(sentences[start:]).strip()
    if last:
        chunks.append(last)

    log.debug(f"  Semantic split: {len(sentences)} sentences → {len(chunks)} chunks")
    return chunks if chunks else [text]


def _recursive_split(text: str) -> List[str]:
    """
    LangChain RecursiveCharacterTextSplitter.
    Splits on paragraphs → sentences → words → chars.
    Best general-purpose fallback splitter.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size * 4,       # chars (approx 1 token = 4 chars)
        chunk_overlap=settings.chunk_overlap * 4,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def _token_split(text: str) -> List[str]:
    """
    LangChain TokenTextSplitter using tiktoken cl100k_base.
    Splits on exact token counts.
    """
    splitter = TokenTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        encoding_name="cl100k_base",
    )
    return splitter.split_text(text)


def _sentence_split(text: str) -> List[str]:
    """Sentence-aware splitting with overlap."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current, current_len = [], [], 0
    for sent in sentences:
        sent_len = _approx_tokens(sent)
        if current_len + sent_len > settings.chunk_size and current:
            chunks.append(" ".join(current))
            overlap, overlap_len = [], 0
            for s in reversed(current):
                sl = _approx_tokens(s)
                if overlap_len + sl <= settings.chunk_overlap:
                    overlap.insert(0, s)
                    overlap_len += sl
                else:
                    break
            current, current_len = overlap, overlap_len
        current.append(sent)
        current_len += sent_len
    if current:
        chunks.append(" ".join(current))
    return chunks


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)