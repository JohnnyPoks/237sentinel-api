"""Model inference, either local (transformers/torch) or remote (HF Inference API).

Set INFERENCE_MODE=hf_api to run on a light host (Render free tier) that has no
torch: the models stay hosted on Hugging Face and we call them over HTTPS with
HF_API_KEY. Set INFERENCE_MODE=local for a big host that loads the models
in-process. Every call degrades to None on failure so the calling service can
fall back to a neutral signal — a rate-limited or unavailable model never
crashes a request.

Return shapes are normalised to match the transformers pipeline outputs the
services already expect:
  * classification  -> list[{"label": str, "score": float}]
  * zero-shot       -> {"labels": [...], "scores": [...]}
  * transcription   -> str
"""
from __future__ import annotations

import time

from app.config import settings
from app.core.logging import get_logger

log = get_logger("inference")

ROUTER = "https://router.huggingface.co/hf-inference/models"


def use_hf_api() -> bool:
    return settings.inference_mode.lower() == "hf_api"


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {settings.hf_api_key}"}
    if extra:
        h.update(extra)
    return h


def _post(url: str, *, json=None, content=None, headers=None, timeout=60):
    """POST with one retry on 503 (model still loading on HF's side)."""
    import httpx

    for attempt in (1, 2, 3):
        r = httpx.post(url, json=json, content=content, headers=headers, timeout=timeout)
        if r.status_code == 503 and attempt < 3:
            wait = min(20, 3 * attempt)
            log.info("HF model loading (503); retrying in %ss", wait)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


# --- Text classification -----------------------------------------------------
def text_classification(model: str, text: str) -> list[dict] | None:
    try:
        data = _post(f"{ROUTER}/{model}", json={"inputs": text}, headers=_headers())
        if data and isinstance(data[0], list):
            data = data[0]
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("hf text-classification failed (%s): %s", model, str(exc)[:120])
        return None


def zero_shot(model: str, text: str, labels: list[str]) -> dict | None:
    try:
        data = _post(
            f"{ROUTER}/{model}",
            json={
                "inputs": text,
                "parameters": {"candidate_labels": labels, "multi_label": True},
            },
            headers=_headers(),
        )
        # Normalise: the API may return {labels,scores} or a list of {label,score}.
        if isinstance(data, dict) and "labels" in data:
            return {"labels": data["labels"], "scores": data["scores"]}
        if isinstance(data, list):
            return {
                "labels": [d["label"] for d in data],
                "scores": [d["score"] for d in data],
            }
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("hf zero-shot failed (%s): %s", model, str(exc)[:120])
        return None


def image_classification(model: str, image_bytes: bytes) -> list[dict] | None:
    try:
        data = _post(
            f"{ROUTER}/{model}",
            content=image_bytes,
            headers=_headers({"Content-Type": "image/jpeg"}),
        )
        if data and isinstance(data[0], list):
            data = data[0]
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("hf image-classification failed (%s): %s", model, str(exc)[:120])
        return None


def audio_classification(model: str, audio_bytes: bytes) -> list[dict] | None:
    try:
        data = _post(
            f"{ROUTER}/{model}",
            content=audio_bytes,
            headers=_headers({"Content-Type": "audio/wav"}),
            timeout=120,
        )
        if data and isinstance(data[0], list):
            data = data[0]
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("hf audio-classification failed (%s): %s", model, str(exc)[:120])
        return None


def transcribe(audio_bytes: bytes, model: str = "openai/whisper-large-v3") -> str | None:
    try:
        data = _post(
            f"{ROUTER}/{model}",
            content=audio_bytes,
            headers=_headers({"Content-Type": "audio/wav"}),
            timeout=180,
        )
        if isinstance(data, dict):
            return data.get("text", "")
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("hf transcription failed: %s", str(exc)[:120])
        return None


# --- Gemini multimodal (Gemini reads images/PDF/audio/video directly) --------
# Inline data caps the whole request at 20 MB; skip larger media and fall back
# to the text path. gemini-2.0-flash accepts image/*, application/pdf, audio/*
# and video/* as inline_data.
GEMINI_INLINE_LIMIT = 18 * 1024 * 1024


def gemini_available() -> bool:
    return bool(settings.gemini_api_key)


def gemini_multimodal(
    prompt: str, media_bytes: bytes, media_mime: str, *, want_json: bool = False
) -> str | None:
    """Send a prompt + one media file to Gemini; return the text reply or None."""
    if not settings.gemini_api_key or not media_bytes:
        return None
    if len(media_bytes) > GEMINI_INLINE_LIMIT:
        log.info("media too large for inline Gemini (%d bytes); skipping", len(media_bytes))
        return None
    try:
        import base64

        import httpx

        model = (
            settings.llm_model if settings.llm_model.startswith("gemini")
            else "gemini-2.0-flash"
        )
        gen: dict = {"temperature": 0.2}
        if want_json:
            gen["responseMimeType"] = "application/json"
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {
                            "mime_type": media_mime,
                            "data": base64.b64encode(media_bytes).decode(),
                        }},
                    ],
                }],
                "generationConfig": gen,
            },
            timeout=90,
        )
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("gemini multimodal failed: %s", str(exc)[:140])
        return None


def ocr_via_gemini(image_bytes: bytes) -> str:
    """Read visible text from an image using Gemini vision (replaces easyocr on
    the light host, which cannot ship torch)."""
    out = gemini_multimodal(
        "Transcribe ALL visible text in this image exactly, preserving line "
        "breaks. Output only the text, nothing else.",
        image_bytes, "image/jpeg",
    )
    return out or ""
