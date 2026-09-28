# """
# app/services/rag_chain.py
# ──────────────────────────
# LangChain RAG chain.

# Wires together:
#   PgVectorRetriever  →  PromptTemplate  →  GroqLLM

# Two modes:
#   1. rag_chain.invoke({"query": "..."})
#      → single-turn answer with sources

#   2. ConversationalRAGChain (multi-turn with memory)
#      → used by chatbot.py
# """
# from __future__ import annotations

# from langchain.chains import RetrievalQA
# from langchain_core.prompts import PromptTemplate
# from langchain_core.runnables import RunnablePassthrough, RunnableParallel
# from langchain_core.output_parsers import StrOutputParser

# from app.services.retriever_service import PgVectorRetriever
# from app.services.llm_service import get_llm
# from app.utils.logger import get_logger

# log = get_logger(__name__)


# # ── Prompt templates ──────────────────────────────────────────────────────

# RAG_PROMPT = PromptTemplate.from_template("""
# You are a helpful assistant that answers questions based strictly on the context below.
# If the answer is not in the context, say so clearly — do not make things up.
# When you use information from a source, cite its URL naturally.

# Context:
# {context}

# Question: {question}

# Answer:""")

# CONDENSE_PROMPT = PromptTemplate.from_template("""
# Given the conversation history and latest question, rewrite it as a standalone search query.
# Output ONLY the search query.

# History:
# {chat_history}

# Question: {question}

# Standalone query:""")


# # ── Context formatter ─────────────────────────────────────────────────────

# def _format_docs(docs) -> str:
#     parts = []
#     for i, doc in enumerate(docs, 1):
#         url = doc.metadata.get("url", "unknown")
#         parts.append(f"SOURCE {i}\nURL: {url}\n{doc.page_content}")
#     return "\n\n---\n\n".join(parts) if parts else "No relevant context found."


# # ── Single-turn RAG chain ─────────────────────────────────────────────────

# def build_rag_chain(top_k: int = None, rerank: bool = True):
#     """
#     Build a single-turn RAG chain.

#     Usage:
#         chain = build_rag_chain()
#         result = chain.invoke({"question": "What is FastEmbed?"})
#         print(result["answer"])
#         print(result["sources"])
#     """
#     retriever = PgVectorRetriever(
#         top_k=top_k or 5,
#         rerank=rerank,
#     )
#     llm = get_llm()

#     # Parallel: retrieve docs + pass question through
#     retrieve_and_question = RunnableParallel(
#         context=retriever | _format_docs,
#         question=RunnablePassthrough(),
#     )

#     chain = (
#         retrieve_and_question
#         | RAG_PROMPT
#         | llm
#         | StrOutputParser()
#     )

#     log.info(f"RAG chain built — top_k={top_k or 5} rerank={rerank}")
#     return chain


# def build_retrieval_qa_chain(top_k: int = None, rerank: bool = True) -> RetrievalQA:
#     """
#     LangChain RetrievalQA chain — returns answer + source_documents.

#     Usage:
#         chain = build_retrieval_qa_chain()
#         result = chain.invoke({"query": "What is pgvector?"})
#         print(result["result"])
#         for doc in result["source_documents"]:
#             print(doc.metadata["url"])
#     """
#     retriever = PgVectorRetriever(top_k=top_k or 5, rerank=rerank)
#     llm = get_llm()

#     chain = RetrievalQA.from_chain_type(
#         llm=llm,
#         chain_type="stuff",
#         retriever=retriever,
#         return_source_documents=True,
#         chain_type_kwargs={"prompt": RAG_PROMPT},
#     )

#     log.info(f"RetrievalQA chain built — top_k={top_k or 5} rerank={rerank}")
#     return chain
"""
app/services/rag_chain.py
──────────────────────────
LangChain RAG chain.

Wires together:
  PgVectorRetriever  →  PromptTemplate  →  GroqLLM

Two modes:
  1. rag_chain.invoke({"query": "..."})
     → single-turn answer with sources

  2. ConversationalRAGChain (multi-turn with memory)
     → used by chatbot.py
"""
from __future__ import annotations

from langchain.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser

from app.services.retriever_service import PgVectorRetriever
from app.services.llm_service import get_llm
from app.utils.logger import get_logger

log = get_logger(__name__)


# ── Prompt templates ──────────────────────────────────────────────────────

# RAG_PROMPT = PromptTemplate.from_template("""
# You are a helpful assistant that answers questions based strictly on the context below.

# RULES:
# - Answer only from the context provided. If the answer is not in the context, say clearly: "I don't have enough information to answer this."
# - Do NOT make up or assume anything not present in the context.
# - Do NOT use markdown tables — they may not render correctly.
# - Format your response using:
#     • Bullet points for lists or multiple items
#     • Short paragraphs for explanations
#     • Bold text (**word**) only for key terms or headings
# - Keep the response clear, concise and easy to read.
# - Cite the source URL naturally at the end of the relevant point or paragraph.

# Context:
# {context}

# Question: {question}

# Answer:""")

RAG_PROMPT = PromptTemplate.from_template("""
You are a helpful assistant that answers questions based strictly on the context below.

STRICT FORMATTING RULES:
- Never use tables under any circumstances.
- Do not include URLs or source links inside the answer text.
- Sources are shown separately below the answer.
- Use bullet points (•) for listing multiple items.
- Use short paragraphs for explanations.
- Use **bold** only for key terms or section headings.
- Keep answers concise and easy to read.

ANSWER RULES:
- Answer only from the context provided.
- If the answer is not in the context say: "I don't have enough information to answer this."
- Do not make up anything not present in the context.
- Cite the source URL naturally at the end of each point like: (source: https://...)

Context:
{context}

Question: {question}

Answer:""")

CONDENSE_PROMPT = PromptTemplate.from_template("""
Given the conversation history and latest question, rewrite it as a standalone search query.
Output ONLY the search query — no explanation, no preamble.

History:
{chat_history}

Question: {question}

Standalone query:""")


# ── Context formatter ─────────────────────────────────────────────────────

# def _format_docs(docs) -> str:
#     parts = []
#     for i, doc in enumerate(docs, 1):
#         url = doc.metadata.get("url", "unknown")
#         parts.append(f"SOURCE {i}\nURL: {url}\n{doc.page_content}")
#     return "\n\n---\n\n".join(parts) if parts else "No relevant context found."


def _format_docs(docs) -> str:
    parts = []
    for doc in docs:
        url = doc.metadata.get("url", "unknown")
        parts.append(f"URL: {url}\n{doc.page_content}")
    return "\n\n---\n\n".join(parts) if parts else "No relevant context found."


# ── Single-turn RAG chain ─────────────────────────────────────────────────

def build_rag_chain(top_k: int = None, rerank: bool = True):
    """
    Build a single-turn RAG chain.

    Usage:
        chain = build_rag_chain()
        result = chain.invoke({"question": "What is FastEmbed?"})
        print(result["answer"])
        print(result["sources"])
    """
    retriever = PgVectorRetriever(
        top_k=top_k or 5,
        rerank=rerank,
    )
    llm = get_llm()

    # Parallel: retrieve docs + pass question through
    retrieve_and_question = RunnableParallel(
        context=retriever | _format_docs,
        question=RunnablePassthrough(),
    )

    chain = (
        retrieve_and_question
        | RAG_PROMPT
        | llm
        | StrOutputParser()
    )

    log.info(f"RAG chain built — top_k={top_k or 5} rerank={rerank}")
    return chain


def build_retrieval_qa_chain(top_k: int = None, rerank: bool = True) -> RetrievalQA:
    """
    LangChain RetrievalQA chain — returns answer + source_documents.

    Usage:
        chain = build_retrieval_qa_chain()
        result = chain.invoke({"query": "What is pgvector?"})
        print(result["result"])
        for doc in result["source_documents"]:
            print(doc.metadata["url"])
    """
    retriever = PgVectorRetriever(top_k=top_k or 5, rerank=rerank)
    llm = get_llm()

    chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": RAG_PROMPT},
    )

    log.info(f"RetrievalQA chain built — top_k={top_k or 5} rerank={rerank}")
    return chain