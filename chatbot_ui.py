# """
# chatbot_ui.py  —  Streamlit chat UI
# ─────────────────────────────────────
# Connects to chatbot.py (FastAPI on :8002).

# Features:
#   - Auto session creation on load
#   - Multi-turn conversation with chat bubbles
#   - Sources expander per answer (URL + chunk count)
#   - Reranker toggle (on/off per message)
#   - top_k slider
#   - One-click evaluation of last response (6 metrics)
#   - Clear history / new session buttons
#   - API health indicator in sidebar

# Usage:
#   streamlit run chatbot_ui.py
# """

# import requests
# import streamlit as st

# # ── Config ────────────────────────────────────────────────────────────────

# API_BASE = "http://localhost:8002"

# # ── Page setup ────────────────────────────────────────────────────────────

# st.set_page_config(
#     page_title="Web Crawler Chatbot",
#     page_icon="🔍",
#     layout="centered",
# )

# st.title("🔍 Web Crawler Chatbot")
# st.caption("Ask questions about crawled web content — powered by pgvector + Groq")

# # ── Session state ─────────────────────────────────────────────────────────

# if "session_id"    not in st.session_state: st.session_state.session_id    = None
# if "messages"      not in st.session_state: st.session_state.messages      = []
# if "last_result"   not in st.session_state: st.session_state.last_result   = None
# if "error"         not in st.session_state: st.session_state.error         = None

# # ── API helpers ───────────────────────────────────────────────────────────

# def api_health() -> bool:
#     try:
#         r = requests.get(f"{API_BASE}/health", timeout=5)
#         return r.status_code == 200
#     except Exception:
#         return False


# def api_create_session() -> str | None:
#     try:
#         r = requests.post(f"{API_BASE}/sessions", timeout=10)
#         r.raise_for_status()
#         return r.json()["session_id"]
#     except Exception as e:
#         st.session_state.error = f"Could not connect to chatbot API: {e}"
#         return None


# def api_chat(session_id: str, message: str,
#              top_k: int, rerank: bool) -> dict | None:
#     try:
#         r = requests.post(
#             f"{API_BASE}/sessions/{session_id}/chat",
#             json={"message": message, "top_k": top_k, "rerank": rerank},
#             timeout=60,
#         )
#         r.raise_for_status()
#         return r.json()
#     except requests.HTTPError as e:
#         st.session_state.error = f"API error {e.response.status_code}: {e.response.text[:200]}"
#     except Exception as e:
#         st.session_state.error = f"Request failed: {e}"
#     return None


# def api_evaluate(session_id: str, reference: str = "") -> dict | None:
#     try:
#         body = {"reference_answer": reference} if reference.strip() else {}
#         r = requests.post(
#             f"{API_BASE}/sessions/{session_id}/evaluate",
#             json=body,
#             timeout=60,
#         )
#         r.raise_for_status()
#         return r.json()
#     except requests.HTTPError as e:
#         st.session_state.error = f"Evaluate error: {e.response.text[:200]}"
#     except Exception as e:
#         st.session_state.error = f"Evaluate failed: {e}"
#     return None


# def api_clear_history(session_id: str):
#     try:
#         requests.delete(f"{API_BASE}/sessions/{session_id}/history", timeout=10)
#     except Exception:
#         pass


# # ── Sidebar ───────────────────────────────────────────────────────────────

# with st.sidebar:
#     st.header("Status")
#     if api_health():
#         st.success("API connected  ✓")
#     else:
#         st.error("API offline — run: python chatbot.py")
#         st.stop()

#     st.divider()
#     st.header("Session")

#     if st.session_state.session_id:
#         sid_short = st.session_state.session_id[:16] + "..."
#         st.info(f"ID: `{sid_short}`")
#         msg_count = len(st.session_state.messages)
#         st.caption(f"{msg_count} message{'s' if msg_count != 1 else ''} in history")

#         col1, col2 = st.columns(2)
#         with col1:
#             if st.button("Clear history", use_container_width=True):
#                 api_clear_history(st.session_state.session_id)
#                 st.session_state.messages   = []
#                 st.session_state.last_result = None
#                 st.rerun()
#         with col2:
#             if st.button("New session", use_container_width=True):
#                 sid = api_create_session()
#                 if sid:
#                     st.session_state.session_id  = sid
#                     st.session_state.messages    = []
#                     st.session_state.last_result = None
#                     st.session_state.error       = None
#                     st.rerun()
#     else:
#         if st.button("Start session", use_container_width=True, type="primary"):
#             sid = api_create_session()
#             if sid:
#                 st.session_state.session_id = sid
#                 st.session_state.error      = None
#                 st.rerun()

#     st.divider()
#     st.header("Settings")

#     top_k = st.slider(
#         "Chunks to retrieve", min_value=1, max_value=15, value=5,
#         help="Number of chunks fetched from pgvector before reranking"
#     )
#     rerank = st.toggle(
#         "Reranker", value=True,
#         help="Cross-encoder reranker (ms-marco-MiniLM-L-6-v2) — improves accuracy"
#     )

#     st.divider()
#     st.header("Evaluate last response")
#     reference = st.text_area(
#         "Reference answer (optional)",
#         placeholder="Paste a ground-truth answer to compute BLEU + ROUGE-L",
#         height=80,
#     )
#     if st.button("Run evaluation", use_container_width=True,
#                  disabled=st.session_state.session_id is None):
#         with st.spinner("Evaluating..."):
#             eval_result = api_evaluate(st.session_state.session_id, reference)
#         if eval_result:
#             m = eval_result.get("metrics", {})
#             st.markdown("**Metrics**")

#             def metric_row(label, val, help_text=""):
#                 if val == -1:
#                     st.caption(f"{label}: *needs reference*")
#                 else:
#                     st.metric(label=label, value=f"{val:.2f}", help=help_text)

#             col1, col2 = st.columns(2)
#             with col1:
#                 metric_row("Faithfulness",     m.get("faithfulness", 0),
#                            "Is answer grounded in context?")
#                 metric_row("Context precision", m.get("context_precision", 0),
#                            "Are retrieved chunks relevant?")
#                 metric_row("BLEU",             m.get("bleu", -1),
#                            "N-gram overlap vs reference")
#             with col2:
#                 metric_row("Answer relevance", m.get("answer_relevance", 0),
#                            "Does answer address the question?")
#                 metric_row("Context recall",   m.get("context_recall", -1),
#                            "Does context cover the answer?")
#                 metric_row("ROUGE-L",          m.get("rouge_l", -1),
#                            "LCS overlap vs reference")

#             overall = m.get("overall_score", 0)
#             st.progress(overall, text=f"Overall score: {overall:.2f}")

#     st.divider()
#     st.caption("FastEmbed AllMiniLM · pgvector · Groq llama3-70b")


# # ── Auto-create session on first load ─────────────────────────────────────

# if st.session_state.session_id is None:
#     with st.spinner("Starting session..."):
#         sid = api_create_session()
#         if sid:
#             st.session_state.session_id = sid
#             st.rerun()

# # Show errors
# if st.session_state.error:
#     st.error(st.session_state.error)
#     st.session_state.error = None

# # ── Chat history ──────────────────────────────────────────────────────────

# for msg in st.session_state.messages:
#     with st.chat_message(msg["role"]):
#         st.markdown(msg["content"].replace("<br>","\n").replace("<br/","\n").replace("<br />","\n"),unsafe_allow_html=True)

#         if msg["role"] == "assistant" and msg.get("sources"):
#             reranked_label = " · reranked" if msg.get("reranked") else ""
#             with st.expander(
#                 f"Sources — {msg['chunks_used']} chunks{reranked_label}",
#                 expanded=False,
#             ):
#                 for url in msg["sources"]:
#                     st.markdown(f"- [{url}]({url})")
#                 if msg.get("search_query"):
#                     st.caption(f"Search query: *{msg['search_query']}*")

# # ── Chat input ────────────────────────────────────────────────────────────

# if prompt := st.chat_input(
#     "Ask anything about the crawled content...",
#     disabled=st.session_state.session_id is None,
# ):
#     # Show user message immediately
#     st.session_state.messages.append({"role": "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     # Call API
#     with st.chat_message("assistant"):
#         with st.spinner("Thinking..."):
#             result = api_chat(
#                 st.session_state.session_id, prompt, top_k, rerank
#             )

#         if result:
#             st.markdown(result["answer"])

#             if result.get("sources"):
#                 reranked_label = " · reranked" if result.get("reranked") else ""
#                 with st.expander(
#                     f"Sources — {result['chunks_used']} chunks{reranked_label}",
#                     expanded=False,
#                 ):
#                     for url in result["sources"]:
#                         st.markdown(f"- [{url}]({url})")
#                     st.caption(f"Search query: *{result['search_query']}*")

#             st.session_state.messages.append({
#                 "role":         "assistant",
#                 "content":      result["answer"],
#                 "sources":      result.get("sources", []),
#                 "chunks_used":  result.get("chunks_used", 0),
#                 "search_query": result.get("search_query", ""),
#                 "reranked":     result.get("reranked", False),
#             })
#             st.session_state.last_result = result
#         else:
#             err = st.session_state.error or "No response — check chatbot.py is running"
#             st.error(err)
#             st.session_state.error = None


"""
chatbot_ui.py  —  Streamlit chat UI (clean chatbot only)
─────────────────────────────────────────────────────────
Connects to chatbot.py (FastAPI on :8002).
Shows only the chat interface — no session ID, chunk size, or reranker controls.

Usage:
  streamlit run chatbot_ui.py
"""

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8002"
TOP_K    = 5      # fixed — no slider shown
RERANK   = False  # fixed — always on, no toggle shown

# ── Page setup ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Web Crawler Chatbot",
    page_icon="",
    layout="centered",
)

st.title("Web Crawler Chatbot")
st.caption("Ask questions about crawled web content — powered by pgvector + Groq")

# ── Session state ─────────────────────────────────────────────────────────

if "session_id"  not in st.session_state: st.session_state.session_id  = None
if "messages"    not in st.session_state: st.session_state.messages    = []
if "last_result" not in st.session_state: st.session_state.last_result = None
if "error"       not in st.session_state: st.session_state.error       = None

# ── API helpers ───────────────────────────────────────────────────────────

def api_health() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def api_create_session() -> str | None:
    try:
        r = requests.post(f"{API_BASE}/sessions", timeout=10)
        r.raise_for_status()
        return r.json()["session_id"]
    except Exception as e:
        st.session_state.error = f"Could not connect to chatbot API: {e}"
        return None


def api_chat(session_id: str, message: str) -> dict | None:
    try:
        r = requests.post(
            f"{API_BASE}/sessions/{session_id}/chat",
            json={"message": message, "top_k": TOP_K, "rerank": RERANK},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        st.session_state.error = f"API error {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        st.session_state.error = f"Request failed: {e}"
    return None


def api_clear_history(session_id: str):
    try:
        requests.delete(f"{API_BASE}/sessions/{session_id}/history", timeout=10)
    except Exception:
        pass


# ── Sidebar — minimal ────────────────────────────────────────────────────

with st.sidebar:
    # API status
    if api_health():
        st.success("API connected ✓")
    else:
        st.error("API offline — run: python chatbot.py")
        st.stop()

    st.divider()

    # Only show clear chat button — no session ID, no settings
    if st.session_state.session_id:
        if st.button("🗑️ Clear chat", use_container_width=True):
            api_clear_history(st.session_state.session_id)
            st.session_state.messages    = []
            st.session_state.last_result = None
            st.rerun()

    st.divider()
    st.caption("FastEmbed AllMiniLM · pgvector · Groq llama3-70b")


# ── Auto-create session on first load ─────────────────────────────────────

if st.session_state.session_id is None:
    with st.spinner("Starting session..."):
        sid = api_create_session()
        if sid:
            st.session_state.session_id = sid
            st.rerun()

# Show errors
if st.session_state.error:
    st.error(st.session_state.error)
    st.session_state.error = None

# ── Chat history ──────────────────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(
            msg["content"].replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n"),
            unsafe_allow_html=True
        )

        # Show sources as a clean expander — no chunk count, no reranker label
        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander("📄 Sources", expanded=False):
                for url in msg["sources"]:
                    st.markdown(f"- [{url}]({url})")

# ── Chat input ────────────────────────────────────────────────────────────

if prompt := st.chat_input(
    "Ask anything about the crawled content...",
    disabled=st.session_state.session_id is None,
):
    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call API and show response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = api_chat(st.session_state.session_id, prompt)

        if result:
            answer = result["answer"].replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            st.markdown(answer, unsafe_allow_html=True)

            # Show sources cleanly
            if result.get("sources"):
                with st.expander("📄 Sources", expanded=False):
                    for url in result["sources"]:
                        st.markdown(f"- [{url}]({url})")

            st.session_state.messages.append({
                "role":    "assistant",
                "content": answer,
                "sources": result.get("sources", []),
            })
            st.session_state.last_result = result
        else:
            err = st.session_state.error or "No response — check chatbot.py is running"
            st.error(err)
            st.session_state.error = None


#netstat -ano | findstr :8501
#taskkill /F /PID 16356

#Get-Process python
# Stop-Process -Id 2280 -Force 