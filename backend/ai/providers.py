"""Phase 8 LLM Provider Interface & Implementations.

Supports pluggable LLM backends:
* FakeLLMProvider (deterministic mock for tests and offline runs)
* OllamaLLMProvider (local Ollama HTTP API)
* HuggingFaceLLMProvider (optional local sentence-transformers / transformers model)
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from backend.config import settings

logger = logging.getLogger("seek.ai.providers")


class LLMProviderError(Exception):
    """Raised when LLM generation fails or times out."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    took_ms: float


class LLMProvider(ABC):
    """Abstract Base Class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier name."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> LLMResult:
        """Generate text response from prompt."""


class FakeLLMProvider(LLMProvider):
    """Deterministic mock provider for offline tests and dry runs."""

    def __init__(self, name: str = "fake", model: str = "seek-fake-v1"):
        self._name = name
        self._model = model

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> LLMResult:
        start = time.perf_counter()
        # Extract question if available
        q_text = ""
        if "USER QUESTION:" in prompt:
            q_text = prompt.split("USER QUESTION:")[-1].replace("ANSWER:", "").strip()

        # Build grounded mock answer with citation [1]
        answer_text = (
            f"Based on the provided search sources, SEEK indexed relevant information regarding "
            f"'{q_text or 'your query'}' [1]. The retrieved documents outline core concepts and technical details [1]."
        )
        took_ms = (time.perf_counter() - start) * 1000.0
        return LLMResult(
            text=answer_text,
            provider=self._name,
            model=self._model,
            took_ms=took_ms,
        )


class OllamaLLMProvider(LLMProvider):
    """Local Ollama HTTP API provider."""

    def __init__(self, host: str | None = None, model: str | None = None):
        self._host = (host or settings.RAG_OLLAMA_HOST).rstrip("/")
        self._model = model or settings.RAG_OLLAMA_MODEL

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> LLMResult:
        start = time.perf_counter()
        temp = temperature if temperature is not None else settings.RAG_TEMPERATURE
        req_timeout = timeout if timeout is not None else settings.RAG_LLM_TIMEOUT_SECONDS

        url = f"{self._host}/api/generate"
        payload = {
            "model": self._model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temp,
            },
        }

        try:
            with httpx.Client(timeout=req_timeout) as client:
                response = client.post(url, json=payload)
                if response.status_code != 200:
                    raise LLMProviderError(
                        f"Ollama returned HTTP {response.status_code}: {response.text}"
                    )
                data = response.json()
                text = str(data.get("response", "")).strip()
                if not text:
                    raise LLMProviderError("Ollama returned empty response")
                took_ms = (time.perf_counter() - start) * 1000.0
                return LLMResult(
                    text=text,
                    provider=self.name,
                    model=self._model,
                    took_ms=took_ms,
                )
        except Exception as exc:
            if isinstance(exc, LLMProviderError):
                raise
            raise LLMProviderError(f"Ollama connection error: {exc}") from exc


class HuggingFaceLLMProvider(LLMProvider):
    """Local Hugging Face transformers pipeline provider."""

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or settings.RAG_TRANSFORMERS_MODEL
        self._pipeline = None

    @property
    def name(self) -> str:
        return "transformers"

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from transformers import pipeline
                self._pipeline = pipeline(
                    "text-generation",
                    model=self._model_name,
                    device_map="auto",
                )
            except Exception as exc:
                raise LLMProviderError(f"Failed to load HuggingFace model '{self._model_name}': {exc}") from exc
        return self._pipeline

    def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> LLMResult:
        start = time.perf_counter()
        pipe = self._get_pipeline()
        full_prompt = f"{system_prompt}\n\n{prompt}"
        try:
            res = pipe(full_prompt, max_new_tokens=256, temperature=temperature or 0.2)
            gen_text = res[0]["generated_text"]
            # Extract generated portion
            answer = gen_text[len(full_prompt):].strip() if gen_text.startswith(full_prompt) else gen_text.strip()
            took_ms = (time.perf_counter() - start) * 1000.0
            return LLMResult(
                text=answer,
                provider=self.name,
                model=self._model_name,
                took_ms=took_ms,
            )
        except Exception as exc:
            raise LLMProviderError(f"HuggingFace inference error: {exc}") from exc


def get_llm_provider(provider_name: str | None = None) -> LLMProvider:
    """Factory function returning configured LLMProvider instance."""
    p_name = (provider_name or settings.RAG_LLM_PROVIDER).lower()
    if p_name == "ollama":
        return OllamaLLMProvider()
    if p_name == "transformers":
        return HuggingFaceLLMProvider()
    return FakeLLMProvider()


__all__ = [
    "LLMProviderError",
    "LLMResult",
    "LLMProvider",
    "FakeLLMProvider",
    "OllamaLLMProvider",
    "HuggingFaceLLMProvider",
    "get_llm_provider",
]
