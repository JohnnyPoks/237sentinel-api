"""Provider-agnostic LLM access with a configurable fallback chain (brief §5).

The chain is set in ONE place via env: LLM_PROVIDER is a comma-separated list
tried left to right, e.g. "gemini,hf_router". Each provider exposes two calls:

  * complete(system, user)                  -> text reasoning
  * complete_vision(prompt, media, mime)    -> reasoning over an image/PDF

On quota (429) or any failure a provider returns NO_LLM and the chain tries the
next one. When every provider returns NO_LLM the semantic/explanation layers fall
back to deterministic rules. So the order is: Gemini -> HF router -> rule-based.

The active provider for the most recent call is recorded on the chain
(`last_used`) and surfaced per request in the analysis result and in /health.
The rest of the codebase never knows which backend answered.
"""
from __future__ import annotations

from typing import Protocol

from app.config import settings
from app.core.logging import get_logger

log = get_logger("llm")

NO_LLM = "__NO_LLM__"


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, want_json: bool = False) -> str: ...

    def complete_vision(
        self, prompt: str, media_bytes: bytes, media_mime: str, *, want_json: bool = False
    ) -> str: ...


class NoneProvider:
    name = "none"

    def complete(self, system, user, *, want_json=False) -> str:
        return NO_LLM

    def complete_vision(self, prompt, media_bytes, media_mime, *, want_json=False) -> str:
        return NO_LLM


class GeminiProvider:
    """Google Gemini (multimodal). Key stays server-side."""

    name = "gemini"

    @staticmethod
    def ready() -> bool:
        return bool(settings.gemini_api_key)

    def complete(self, system, user, *, want_json=False) -> str:
        from app.services.inference import block_gemini, gemini_blocked

        if not self.ready() or gemini_blocked():
            return NO_LLM
        try:
            import httpx

            model = settings.llm_model if settings.llm_model.startswith("gemini") else "gemini-2.0-flash"
            gen: dict = {"temperature": 0.2}
            if want_json:
                gen["responseMimeType"] = "application/json"
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": settings.gemini_api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": gen,
                },
                timeout=45,
            )
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc):
                block_gemini()
            log.warning("gemini completion failed: %s", str(exc)[:120])
            return NO_LLM

    def complete_vision(self, prompt, media_bytes, media_mime, *, want_json=False) -> str:
        if not self.ready():
            return NO_LLM
        from app.services import inference

        out = inference.gemini_multimodal(prompt, media_bytes, media_mime, want_json=want_json)
        return out if out else NO_LLM


class HFRouterProvider:
    """Hugging Face router via the OpenAI SDK. Reuses HF_API_KEY.

    Text  -> hf_router_text_model (Llama-3.3-70B).
    Vision-> hf_router_vision_model (a Llama-4 multimodal model). PDFs are
             rendered to an image first; audio/video are not supported here and
             fall through to the next layer.
    """

    name = "hf_router"

    def __init__(self) -> None:
        self._client = None

    @staticmethod
    def ready() -> bool:
        return bool(settings.hf_api_key)

    def _cli(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=settings.hf_router_base_url, api_key=settings.hf_api_key
            )
        return self._client

    def complete(self, system, user, *, want_json=False) -> str:
        if not self.ready():
            return NO_LLM
        try:
            kwargs = {}
            if want_json:
                kwargs["response_format"] = {"type": "json_object"}
            r = self._cli().chat.completions.create(
                model=settings.hf_router_text_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=1024,
                **kwargs,
            )
            return r.choices[0].message.content or NO_LLM
        except Exception as exc:  # noqa: BLE001
            log.warning("hf_router completion failed: %s", str(exc)[:140])
            return NO_LLM

    def complete_vision(self, prompt, media_bytes, media_mime, *, want_json=False) -> str:
        if not self.ready():
            return NO_LLM
        import base64

        img_bytes, mime = media_bytes, media_mime
        # These vision models take images, not PDFs — render the first PDF page.
        if media_mime == "application/pdf":
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(stream=media_bytes, filetype="pdf")
                img_bytes = doc[0].get_pixmap(dpi=150).tobytes("png")
                mime = "image/png"
                doc.close()
            except Exception:  # noqa: BLE001
                return NO_LLM
        elif not media_mime.startswith("image/"):
            return NO_LLM  # audio/video: let the next layer handle it

        try:
            b64 = base64.b64encode(img_bytes).decode()
            kwargs = {}
            if want_json:
                kwargs["response_format"] = {"type": "json_object"}
            r = self._cli().chat.completions.create(
                model=settings.hf_router_vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }],
                temperature=0.2,
                max_tokens=1024,
                **kwargs,
            )
            return r.choices[0].message.content or NO_LLM
        except Exception as exc:  # noqa: BLE001
            log.warning("hf_router vision failed: %s", str(exc)[:140])
            return NO_LLM


class AnthropicProvider:
    name = "anthropic"

    @staticmethod
    def ready() -> bool:
        return bool(settings.anthropic_api_key)

    def complete(self, system, user, *, want_json=False) -> str:
        if not self.ready():
            return NO_LLM
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            msg = client.messages.create(
                model=settings.llm_model or "claude-sonnet-5",
                max_tokens=1024, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in msg.content if b.type == "text")
        except Exception as exc:  # noqa: BLE001
            log.warning("anthropic completion failed: %s", str(exc)[:120])
            return NO_LLM

    def complete_vision(self, prompt, media_bytes, media_mime, *, want_json=False) -> str:
        return NO_LLM


_REGISTRY: dict[str, type] = {
    "gemini": GeminiProvider,
    "hf_router": HFRouterProvider,
    "anthropic": AnthropicProvider,
    "none": NoneProvider,
}


class LLMChain:
    """Tries providers in order; records which one answered (`last_used`)."""

    name = "chain"

    def __init__(self, providers: list) -> None:
        self.providers = providers
        self.last_used: str | None = None

    def complete(self, system, user, *, want_json=False) -> str:
        self.last_used = None
        for p in self.providers:
            out = p.complete(system, user, want_json=want_json)
            if out and out != NO_LLM:
                self.last_used = p.name
                return out
        return NO_LLM

    def complete_vision(self, prompt, media_bytes, media_mime, *, want_json=False) -> str:
        self.last_used = None
        for p in self.providers:
            out = p.complete_vision(prompt, media_bytes, media_mime, want_json=want_json)
            if out and out != NO_LLM:
                self.last_used = p.name
                return out
        return NO_LLM

    def status(self) -> dict:
        return {
            "chain": [p.name for p in self.providers],
            "ready": {
                p.name: (p.ready() if hasattr(p, "ready") else True)
                for p in self.providers
            },
            "fallback": "rule-based",
        }


_chain: LLMChain | None = None


def get_llm() -> LLMChain:
    global _chain
    if _chain is not None:
        return _chain
    names = [n.strip().lower() for n in (settings.llm_provider or "none").split(",") if n.strip()]
    providers = []
    for n in names:
        cls = _REGISTRY.get(n)
        if cls and n != "none":
            try:
                providers.append(cls())
            except Exception as exc:  # noqa: BLE001
                log.warning("provider %s init failed: %s", n, exc)
    if not providers:
        providers = [NoneProvider()]
    _chain = LLMChain(providers)
    log.info("LLM chain: %s", " -> ".join(p.name for p in providers) + " -> rule-based")
    return _chain
