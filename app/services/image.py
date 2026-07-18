"""Image service (brief §6).

EXIF inspection, Error Level Analysis, the ViT deepfake classifier, and OCR
(text handed to the text service). This is the forged-communiqué check.

IMPORTANT: ELA is ONE signal among several and is NEVER the headline. It is
unreliable alone on modern re-encoded images (every WhatsApp image is
re-encoded), so it is weighted down in config and the verification engine will
not raise ALTERED on ELA alone. See config.Thresholds.ELA_WEIGHT.
"""
from __future__ import annotations

import io

from app.core.logging import get_logger
from app.schemas.analysis import ContentType, ServiceOutput, Signal

log = get_logger("image")


def _load(image_bytes: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def _exif_signal(image_bytes: bytes) -> Signal:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        img = Image.open(io.BytesIO(image_bytes))
        exif = getattr(img, "_getexif", lambda: None)() or {}
        software = None
        for tag_id, value in exif.items():
            if TAGS.get(tag_id) == "Software":
                software = str(value)
        edited = bool(software and any(
            e in software.lower() for e in ("photoshop", "gimp", "canva", "paint")
        ))
        return Signal(
            name="exif",
            label=(
                "The image says it was edited in photo software"
                if edited
                else "The image's hidden details look ordinary"
            ),
            risk=0.45 if edited else 0.1,
            direction="risk" if edited else "neutral",
            detail=f"Editing software tag: {software}" if software else "No editing software tag.",
            raw={"software": software, "has_exif": bool(exif), "forensic": True},
        )
    except Exception as exc:  # noqa: BLE001
        return Signal(
            name="exif", label="Could not read the image's hidden details",
            risk=0.2, direction="neutral", detail="EXIF unavailable.",
            raw={"error": str(exc)[:120], "forensic": True},
        )


def _ela_signal(image_bytes: bytes) -> Signal:
    """Resave at 95% JPEG, diff, look for localized error spikes.

    Deliberately conservative and down-weighted (see module docstring).
    """
    try:
        from PIL import Image, ImageChops
        import numpy as np

        orig = _load(image_bytes)
        buf = io.BytesIO()
        orig.save(buf, "JPEG", quality=95)
        buf.seek(0)
        resaved = Image.open(buf).convert("RGB")
        diff = ImageChops.difference(orig, resaved)
        arr = np.asarray(diff, dtype="float32")
        # Spike-to-mean ratio: localized alteration shows as bright regions.
        mean = float(arr.mean()) + 1e-6
        p99 = float(np.percentile(arr, 99))
        ratio = p99 / mean
        # ratio ~ up to ~8 is normal; higher hints at pasted regions.
        risk = max(0.0, min(1.0, (ratio - 6.0) / 12.0))
        return Signal(
            name="ela",
            label="Parts of the image compress differently from the rest",
            risk=round(risk, 3),
            direction="risk" if risk >= 0.55 else "neutral",
            detail="Uneven compression can indicate a pasted stamp or signature (weak signal alone).",
            raw={"ratio": round(ratio, 2), "forensic": True, "weak_alone": True},
        )
    except Exception as exc:  # noqa: BLE001
        return Signal(
            name="ela", label="Could not run the compression check",
            risk=0.2, direction="neutral", detail="ELA unavailable.",
            raw={"error": str(exc)[:120], "forensic": True},
        )


def _classifier_signal(image_bytes: bytes) -> Signal:
    try:
        from app.services.model_loader import image_classifier

        clf = image_classifier()
        preds = clf(_load(image_bytes))
        if preds and isinstance(preds[0], list):
            preds = preds[0]
        scores = {p["label"].lower(): float(p["score"]) for p in preds}
        fake = max(
            (v for k, v in scores.items() if any(
                t in k for t in ("fake", "deepfake", "manipulat", "synthetic", "label_1")
            )),
            default=0.0,
        )
        return Signal(
            name="image_classifier",
            label="Signs this image was synthetically generated"
            if fake >= 0.7 else "No strong sign of synthetic generation",
            risk=round(fake, 3),
            direction="risk" if fake >= 0.7 else "neutral",
            detail="Automated image-manipulation check.",
            raw={"scores": scores, "forensic": True},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("image classifier unavailable: %s", exc)
        return Signal(
            name="image_classifier", label="Automated image check was unavailable",
            risk=0.25, direction="neutral", detail="Image model could not load.",
            raw={"error": str(exc)[:120], "forensic": True},
        )


def _ocr_text(image_bytes: bytes) -> str:
    try:
        import numpy as np

        from app.services.model_loader import ocr_reader

        reader = ocr_reader()
        arr = np.asarray(_load(image_bytes))
        lines = reader.readtext(arr, detail=0, paragraph=True)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        log.info("OCR unavailable: %s", exc)
        return ""


def analyze(image_bytes: bytes, db=None) -> ServiceOutput:
    from app.services import text as text_service

    signals = [
        _exif_signal(image_bytes),
        _ela_signal(image_bytes),
        _classifier_signal(image_bytes),
    ]
    text = _ocr_text(image_bytes)
    sub_outputs = []
    if text.strip():
        sub = text_service.analyze(text, db)
        sub_outputs.append(sub)
        signals.extend(sub.signals)

    return ServiceOutput(
        content_type=ContentType.image,
        extracted_text=text or None,
        signals=signals,
        sub_outputs=sub_outputs,
        notes=["OCR text extracted" if text.strip() else "no readable text found"],
    )
