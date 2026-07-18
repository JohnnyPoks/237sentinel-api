"""Lazy, cached model loaders.

Never load models at import — a free Space will OOM if every classifier loads
eagerly. Each loader is a singleton: the first call pays the load cost (logged),
subsequent calls reuse the cached pipeline. If `transformers`/`torch` are not
installed or a load fails, loaders raise and the calling service degrades to an
"unknown" signal rather than crashing the request.
"""
from __future__ import annotations

import threading
from typing import Any

from app.config import Models
from app.core.logging import get_logger, log_duration

log = get_logger("model_loader")

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _load(key: str, builder) -> Any:
    """Thread-safe singleton load. `builder` returns the heavy object."""
    if key in _cache:
        return _cache[key]
    with _lock:
        if key in _cache:  # double-checked
            return _cache[key]
        with log_duration(log, f"load model '{key}'"):
            obj = builder()
        _cache[key] = obj
        return obj


def link_classifier():
    def build():
        from transformers import pipeline

        try:
            return pipeline("text-classification", model=Models.LINK, top_k=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("primary link model failed (%s); using fallback", exc)
            return pipeline(
                "text-classification", model=Models.LINK_FALLBACK, top_k=None
            )

    return _load("link", build)


def text_zeroshot():
    def build():
        from transformers import pipeline

        return pipeline("zero-shot-classification", model=Models.TEXT_ZEROSHOT)

    return _load("text_zeroshot", build)


def image_classifier():
    def build():
        from transformers import pipeline

        try:
            return pipeline("image-classification", model=Models.IMAGE, top_k=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("primary image model failed (%s); using alt", exc)
            return pipeline(
                "image-classification", model=Models.IMAGE_ALT, top_k=None
            )

    return _load("image", build)


def audio_classifier():
    def build():
        from transformers import pipeline

        try:
            return pipeline("audio-classification", model=Models.AUDIO, top_k=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("primary audio model failed (%s); using fallback", exc)
            return pipeline(
                "audio-classification", model=Models.AUDIO_FALLBACK, top_k=None
            )

    return _load("audio", build)


def whisper_model():
    def build():
        from faster_whisper import WhisperModel

        # int8 keeps memory low on a CPU Space.
        return WhisperModel(Models.WHISPER, device="cpu", compute_type="int8")

    return _load("whisper", build)


def ocr_reader():
    def build():
        import easyocr

        return easyocr.Reader(["en", "fr"], gpu=False)

    return _load("ocr", build)
