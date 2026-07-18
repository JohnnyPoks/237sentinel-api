"""Pre-fetch model weights at Docker build time (brief §10).

Only the two primary-path models (link classifier + text zero-shot) are fetched
by default, so the image stays a reasonable size and the build does not time
out. The heavier media models (image, audio, whisper, OCR) download lazily on
first use — a deliberate trade-off documented in docs/MODELS.md and the README.

Override the set with PREFETCH_MODELS=link,text,image,audio (comma-separated).
Any failure here is logged and ignored: the app still works, just with a slower
first call for that modality.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Models  # noqa: E402

DEFAULT = "link,text"


def main() -> None:
    which = os.environ.get("PREFETCH_MODELS", DEFAULT).split(",")
    which = [w.strip() for w in which if w.strip()]

    def fetch(kind: str) -> None:
        from transformers import AutoModel, AutoTokenizer, pipeline

        try:
            if kind == "link":
                pipeline("text-classification", model=Models.LINK)
            elif kind == "text":
                AutoTokenizer.from_pretrained(Models.TEXT_ZEROSHOT)
                AutoModel.from_pretrained(Models.TEXT_ZEROSHOT)
            elif kind == "image":
                pipeline("image-classification", model=Models.IMAGE)
            elif kind == "audio":
                pipeline("audio-classification", model=Models.AUDIO)
            print(f"prefetched: {kind}")
        except Exception as exc:  # noqa: BLE001
            print(f"prefetch failed for {kind}: {exc}")

    for kind in which:
        fetch(kind)


if __name__ == "__main__":
    main()
