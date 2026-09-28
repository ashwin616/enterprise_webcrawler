"""
app/services/llm_service.py
────────────────────────────
GroqLLM wrapped as a LangChain BaseLLM.
Used directly OR via LangChain chains.

Usage:
    from app.services.llm_service import GroqLLM, get_llm
    llm = get_llm()
    answer = llm.invoke("What is LangChain?")
"""
from __future__ import annotations
from typing import Any, List, Optional
from langchain_core.language_models.llms import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from config.settings import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


class GroqLLM(LLM):
    """
    LangChain-compatible wrapper for Groq API.
    Supports direct .invoke() and use inside LangChain chains.
    """
    model:       str   = settings.groq_model
    temperature: float = 0.1
    top_p:       float = 0.7
    max_tokens:  int   = 1024
    api_key:     str   = settings.groq_api_key

    @property
    def _llm_type(self) -> str:
        return "groq"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        from groq import Groq
        client = Groq(api_key=self.api_key)
        params = {
            "model":       self.model,
            "temperature": self.temperature,
            "top_p":       self.top_p,
            "max_tokens":  self.max_tokens,
            "stream":      False,
        }
        if stop:
            params["stop"] = stop

        log.debug(f"Calling Groq model={self.model} prompt_len={len(prompt)}")
        response = client.chat.completions.create(
            messages=[{"role": "system", "content": prompt}],
            **params,
        )
        result = response.choices[0].message.content
        log.debug(f"Groq response len={len(result)}")
        return result

    @property
    def _identifying_params(self) -> dict:
        return {"model": self.model, "temperature": self.temperature}


_llm_instance: GroqLLM | None = None


def get_llm() -> GroqLLM:
    """Return singleton LLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = GroqLLM()
        log.info(f"GroqLLM initialised — model={_llm_instance.model}")
    return _llm_instance
