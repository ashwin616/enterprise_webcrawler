"""
chatbot.py  —  RAG Chatbot API (LangChain edition)
────────────────────────────────────────────────────
Multi-turn conversational RAG.

Pipeline per message:
  1. Condense query using history   (Groq LLM)
  2. PgVectorRetriever              (FastEmbed → pgvector cosine search)
  3. Cross-encoder reranker         (ms-marco-MiniLM-L-6-v2)
  4. LangChain RAG chain            (PromptTemplate → GroqLLM)
  5. Session memory                 (in-memory, max 20 messages)

Endpoints:
  POST /sessions                    → create session
  POST /sessions/{id}/chat          → send message, get answer
  POST /sessions/{id}/evaluate      → evaluate last response
  GET  /sessions/{id}/history       → conversation history
  DELETE /sessions/{id}/history     → clear history
  DELETE /sessions/{id}             → delete session
  GET  /health                      → health check

Usage:
  python chatbot.py
"""
from __future__ import annotations

import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.services.retriever_service import retrieve
from app.services.llm_service import get_llm
from app.services.evaluation import evaluate_rag_response
from app.services.database import init_schema
from app.utils.logger import get_logger
from config.settings import settings

log = get_logger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────

# SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on
# content fetched from web pages. Use the retrieved context below to answer.
# If the answer is not in the context, say so clearly — do not make things up.
# When you use information from a source, naturally cite its URL in your answer."""

# CONDENSE_PROMPT = """Given the conversation history and the latest user message,
# write a single standalone search query. Output ONLY the query, nothing else.

# History:
# {history}

# Message: {message}"""

SYSTEM_PROMPT = """You are a helpful assistant that answers questions strictly based on
content fetched from web pages.

GREETING RULES:
- If the user says hi, hello, hey or any greeting — respond warmly and briefly.
- If the user says bye, goodbye, thank you or any closing — respond politely and briefly.
- For greetings and closings do NOT look at the context — just respond naturally.

STRICT FORMATTING RULES:
- Never use tables under any circumstances.
- Do not include URLs or source links inside the answer text.
- Sources are shown separately below the answer.
- Use bullet points (•) for listing multiple items and use new line for next points.
- Each bullet point must be on its own separate line with a line break after it.
- Never put multiple bullet points on the same line.
- Use short paragraphs for explanations.
- Use **bold** only for key terms or section headings.
- Keep answers concise and easy to read.
- If multiple bullet points come from the same URL, cite the URL once at the end 
  of that section — not after every single bullet point.

ANSWER RULES:
- Answer only from the retrieved context provided.
- If the answer is not in the context say: "I don't have enough information to answer this."
- Do not make up anything not present in the context.
- Cite the source URL naturally at the end of each point like: (source: https://...)"""

CONDENSE_PROMPT = """Given the conversation history and the latest user message,
write a single standalone search query. Output ONLY the query, nothing else.
No explanation, no preamble, no tables.

History:
{history}

Message: {message}"""

# ── Session store ─────────────────────────────────────────────────────────

class SessionStore:
    def __init__(self):
        self._sessions: dict = {}

    def create(self) -> str:
        sid = str(uuid.uuid4())
        self._sessions[sid] = {
            "messages": [], "created_at": _now(), "last_active": _now(),
            "last_chunks": [], "last_answer": "", "last_query": "",
        }
        log.info(f"Session created: {sid[:16]}")
        return sid

    def exists(self, sid: str) -> bool:
        return sid in self._sessions

    def get(self, sid: str) -> dict | None:
        return self._sessions.get(sid)

    def delete(self, sid: str):
        self._sessions.pop(sid, None)

    def list_all(self) -> list:
        return [
            {"session_id": k, "message_count": len(v["messages"]),
             "last_active": v["last_active"]}
            for k, v in self._sessions.items()
        ]

    def add_message(self, sid: str, role: str, content: str):
        s = self._sessions.setdefault(sid, {
            "messages": [], "created_at": _now(), "last_active": _now(),
            "last_chunks": [], "last_answer": "", "last_query": "",
        })
        s["messages"].append({"role": role, "content": content, "timestamp": _now()})
        s["last_active"] = _now()
        if len(s["messages"]) > settings.chatbot_max_history:
            s["messages"] = s["messages"][-settings.chatbot_max_history:]

    def get_messages(self, sid: str) -> list:
        return self._sessions.get(sid, {}).get("messages", [])

    def get_llm_history(self, sid: str) -> list:
        return [{"role": m["role"], "content": m["content"]}
                for m in self.get_messages(sid)]

    def clear(self, sid: str):
        if sid in self._sessions:
            self._sessions[sid]["messages"] = []

    def save_last_response(self, sid: str, query: str, answer: str, chunks: list):
        if sid in self._sessions:
            self._sessions[sid]["last_query"]  = query
            self._sessions[sid]["last_answer"] = answer
            self._sessions[sid]["last_chunks"] = chunks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


store = SessionStore()


# ── Helper functions ──────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"[\u3010\u3011\[][\d\w\u2020†:,\-]+[\u3011\u3010\]]", "", text)
    text = re.sub(r"\u2020[\w\-:]+", "", text)
    return re.sub(r" {2,}", " ", text).strip()


def condense_query(session_id: str, message: str) -> str:
    history = store.get_llm_history(session_id)
    prior   = [m for m in history[:-1] if m["role"] in ("user", "assistant")]
    if not prior:
        return message
    history_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in prior[-6:])
    try:
        llm = get_llm()
        condensed = llm.invoke(
            CONDENSE_PROMPT.format(history=history_text, message=message)
        )
        return condensed.strip() or message
    except Exception:
        return message


def build_context(chunks: list) -> str:
    if not chunks:
        return "No relevant content found."
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"SOURCE {i}\nURL: {c.get('url','')}\n{_clean(c['content'])}")
    return "\n\n---\n\n".join(parts)


def answer(session_id: str, message: str, chunks: list) -> str:
    context  = build_context(chunks)
    history  = store.get_llm_history(session_id)
    llm      = get_llm()

    messages_for_llm = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history[:-1]
        + [{"role": "system", "content": f"Relevant context:\n\n{context}"}]
        + [history[-1]]
    )
    full_prompt = "\n\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages_for_llm
    )
    return _clean(llm.invoke(full_prompt))


# ── FastAPI ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="RAG Chatbot API",
    description="Multi-turn RAG with pgvector + reranker + LangChain",
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message:str
    top_k:      Optional[int]   = settings.retrieval_top_k
    rerank:     Optional[bool]  = True


class ChatResponse(BaseModel):
    session_id:     str
    answer:         str
    sources:        list[str]
    chunks_used:    int
    search_query:   str
    history_length: int
    model:          str
    reranked:       bool


class EvalRequest(BaseModel):
    reference_answer: Optional[str] = None


# ── Session endpoints ─────────────────────────────────────────────────────

@app.post("/sessions", status_code=201)
def create_session():
    sid = store.create()
    return {"session_id": sid, "message": "Session created"}


@app.get("/sessions")
def list_sessions():
    return {"sessions": store.list_all()}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if not store.exists(session_id):
        raise HTTPException(404, "Session not found")
    store.delete(session_id)
    return {"message": f"Session {session_id} deleted"}


# ── Chat ──────────────────────────────────────────────────────────────────

@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
def chat(session_id: str, req: ChatRequest):
    if not store.exists(session_id):
        raise HTTPException(404, "Session not found. POST /sessions first.")
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")

    # 1. Save user message
    store.add_message(session_id, "user", req.message)

    # 2. Condense query using history
    search_query = condense_query(session_id, req.message)
    log.info(f"[{session_id[:8]}] search='{search_query[:80]}'")

    print("rephrased query is ",search_query)

    # 3. Retrieve + rerank via pgvector
    chunks = retrieve(
        query=search_query,
        top_k=req.top_k,
        rerank_results=req.rerank,
    )


    # 4. LangChain prompt → Groq answer
    reply = answer(session_id, req.message, chunks)

    print("reply==>",reply)

    # 5. Save assistant reply + chunks for evaluation
    store.add_message(session_id, "assistant", reply)
    store.save_last_response(session_id, search_query, reply, chunks)

    print("chunks==>",chunks)

    sources = list({c["url"] for c in chunks if c.get("url")})
    log.info(f"[{session_id[:8]}] answered chunks={len(chunks)} sources={len(sources)}")

    return ChatResponse(
        session_id     = session_id,
        answer         = reply,
        sources        = sources,
        chunks_used    = len(chunks),
        search_query   = search_query,
        history_length = len(store.get_messages(session_id)),
        model          = settings.groq_model,
        reranked       = req.rerank and len(chunks) > 0,
    )


# ── Evaluation endpoint ───────────────────────────────────────────────────

@app.post("/sessions/{session_id}/evaluate")
def evaluate_last_response(session_id: str, req: EvalRequest):
    """
    Evaluate the last response in a session.

    Metrics returned:
      - faithfulness      (0-1) — is answer grounded in context?
      - answer_relevance  (0-1) — does answer address the question?
      - context_precision (0-1) — are retrieved chunks relevant?
      - context_recall    (0-1) — does context cover the answer? (needs reference)
      - bleu              (0-1) — n-gram overlap vs reference
      - rouge_l           (0-1) — LCS overlap vs reference
      - overall_score     (0-1) — weighted average
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    query  = session.get("last_query", "")
    answer_text = session.get("last_answer", "")
    chunks = session.get("last_chunks", [])



    print("=====")
    print(answer_text)
    if not query or not answer_text:
        raise HTTPException(400, "No response to evaluate yet. Send a chat message first.")

    log.info(f"[{session_id[:8]}] Running evaluation...")
    metrics = evaluate_rag_response(
        query=query,
        answer=answer_text,
        chunks=chunks,
        reference_answer=req.reference_answer,
    )
    return {"session_id": session_id, "query": query, "metrics": metrics}


# ── History ───────────────────────────────────────────────────────────────

@app.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    if not store.exists(session_id):
        raise HTTPException(404, "Session not found")
    msgs = store.get_messages(session_id)
    return {"session_id": session_id, "message_count": len(msgs), "messages": msgs}


@app.delete("/sessions/{session_id}/history")
def clear_history(session_id: str):
    if not store.exists(session_id):
        raise HTTPException(404, "Session not found")
    store.clear(session_id)
    return {"message": "History cleared"}


@app.get("/health")
def health():
    return {
        "status": "ok", "service": "chatbot",
        "model": settings.groq_model,
        "active_sessions": len(store.list_all()),
    }


if __name__ == "__main__":
    import uvicorn
    init_schema()
    log.info(f"Chatbot API starting on port {settings.chatbot_api_port}")
    uvicorn.run("chatbot:app", host=settings.app_host,
                port=settings.chatbot_api_port,
                reload=settings.app_env == "development")
