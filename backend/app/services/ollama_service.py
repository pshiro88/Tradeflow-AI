"""The ONLY module that talks to Ollama (BRD architecture rule 7).

The browser never reaches Ollama; the rest of the backend depends on the small `LLMClient` protocol below,
so tests inject a scripted fake and the app keeps working (with fallbacks) when Ollama is down.
"""

import json
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import AIResponseError, AIUnavailableError


class LLMClient(Protocol):
    model: str

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON object constrained to `schema`."""

    def chat_text(self, system: str, user: str) -> str:
        """Return a short plain-text completion."""

    def is_available(self) -> bool:
        """True when Ollama answers and the configured model is installed."""


class OllamaService:
    """Thin httpx client for Ollama's local HTTP API. Temperature 0 keeps output as repeatable as possible."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            transport=transport,
        )

    # ------------------------------------------------------------------ public API

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        content = self._chat(system, user, response_format=schema)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIResponseError("The AI model returned something that was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise AIResponseError("The AI model returned JSON of the wrong shape")
        return parsed

    def chat_text(self, system: str, user: str) -> str:
        content = self._chat(system, user, response_format=None).strip()
        if not content:
            raise AIResponseError("The AI model returned an empty answer")
        return content

    def is_available(self) -> bool:
        try:
            response = self._client.get("/api/tags", timeout=3.0)
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError):
            return False
        return self.model in names or f"{self.model}:latest" in names

    # ------------------------------------------------------------------ internals

    def _chat(self, system: str, user: str, *, response_format: dict[str, Any] | None) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "seed": 7},
        }
        if response_format is not None:
            body["format"] = response_format  # Ollama structured outputs: constrain generation to this JSON schema
        try:
            response = self._client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise AIUnavailableError("The AI model took too long to respond. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise AIUnavailableError("The local AI service (Ollama) is not reachable. Is it running?") from exc

        if response.status_code == 404:
            raise AIUnavailableError(f"The AI model '{self.model}' is not installed. Run: ollama pull {self.model}")
        if response.status_code >= 400:
            raise AIUnavailableError(f"The AI service returned an error (HTTP {response.status_code}).")
        try:
            return str(response.json()["message"]["content"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AIResponseError("The AI service returned an unexpected response") from exc


@lru_cache
def _default_client() -> OllamaService:
    settings = get_settings()
    return OllamaService(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds)


def get_llm() -> LLMClient:
    """FastAPI dependency. Tests override it with a scripted fake via app.dependency_overrides."""
    return _default_client()
