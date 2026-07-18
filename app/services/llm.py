"""Provider-agnostic LLM access (brief §5).

The rest of the codebase never knows which backend is in use. Swap via env:
LLM_PROVIDER = anthropic | openai | hf | none.

`none` is a first-class provider: it returns a sentinel so the semantic and
explanation layers fall back to deterministic, rule-based output. This means
the whole app runs with zero API keys — the default — and the demo never dies
because a key is missing or a provider is rate-limited.
"""
from __future__ import annotations

from typing import Protocol

from app.config import settings
from app.core.logging import get_logger

log = get_logger("llm")

# Sentinel returned by the `none` provider and on hard failure.
NO_LLM = "__NO_LLM__"


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, want_json: bool = False) -> str:
        ...


class NoneProvider:
    """No LLM configured. Callers must handle NO_LLM by degrading gracefully."""

    name = "none"

    def complete(self, system: str, user: str, *, want_json: bool = False) -> str:
        return NO_LLM


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model or "claude-sonnet-5"

    def complete(self, system: str, user: str, *, want_json: bool = False) -> str:
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(
                block.text for block in msg.content if block.type == "text"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("anthropic completion failed: %s", exc)
            return NO_LLM


class OpenAIProvider:
    """Works with OpenAI and any OpenAI-compatible endpoint (set OPENAI_BASE_URL)."""

    name = "openai"

    def __init__(self) -> None:
        import httpx

        self._base = (settings.openai_base_url or "https://api.openai.com/v1").rstrip(
            "/"
        )
        self._key = settings.openai_api_key
        self._model = settings.llm_model or "gpt-4o-mini"
        self._http = httpx.Client(timeout=30.0)

    def complete(self, system: str, user: str, *, want_json: bool = False) -> str:
        try:
            body = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
            }
            if want_json:
                body["response_format"] = {"type": "json_object"}
            r = self._http.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json=body,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            log.warning("openai completion failed: %s", exc)
            return NO_LLM


class HFProvider:
    """Hugging Face Inference API (chat-completions compatible route)."""

    name = "hf"

    def __init__(self) -> None:
        import httpx

        self._key = settings.hf_api_key
        self._model = settings.llm_model or "meta-llama/Llama-3.1-8B-Instruct"
        self._http = httpx.Client(timeout=45.0)

    def complete(self, system: str, user: str, *, want_json: bool = False) -> str:
        try:
            url = f"https://api-inference.huggingface.co/models/{self._model}/v1/chat/completions"
            r = self._http.post(
                url,
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            log.warning("hf completion failed: %s", exc)
            return NO_LLM


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is not None:
        return _provider
    choice = (settings.llm_provider or "none").lower()
    try:
        if choice == "anthropic" and settings.anthropic_api_key:
            _provider = AnthropicProvider()
        elif choice == "openai" and settings.openai_api_key:
            _provider = OpenAIProvider()
        elif choice == "hf" and settings.hf_api_key:
            _provider = HFProvider()
        else:
            _provider = NoneProvider()
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM provider init failed (%s); using none", exc)
        _provider = NoneProvider()
    log.info("LLM provider: %s", _provider.name)
    return _provider
