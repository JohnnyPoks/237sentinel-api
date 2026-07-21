"""Audio service (brief §6).

Accepts mp3/wav/ogg/m4a (WhatsApp sends ogg). Normalises to 16 kHz mono wav
with ffmpeg, runs the wav2vec2 synthesis detector, transcribes with
faster-whisper, and passes the transcript to the text service.

Honesty note: the published detector accuracy is a lab figure on clean studio
data. WhatsApp voice notes recorded in a market are much harder; we report a
band, not a percentage. See docs/MODELS.md.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from app.core.logging import get_logger
from app.schemas.analysis import ContentType, ServiceOutput, Signal

log = get_logger("audio")


def _to_wav(audio_bytes: bytes, suffix: str) -> str | None:
    """ffmpeg-normalise to 16 kHz mono wav. Returns path or None on failure."""
    src = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    src.write(audio_bytes)
    src.close()
    dst = src.name + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", src.name, "-ar", "16000", "-ac", "1", dst],
            check=True, capture_output=True, timeout=120,
        )
        return dst
    except Exception as exc:  # noqa: BLE001
        log.warning("ffmpeg normalise failed: %s", exc)
        return None
    finally:
        try:
            os.unlink(src.name)
        except OSError:
            pass


def _synthesis_signal(wav_path: str) -> Signal:
    try:
        from app.config import Models
        from app.services import inference

        if inference.use_hf_api():
            with open(wav_path, "rb") as f:
                preds = inference.audio_classification(Models.AUDIO, f.read())
            if not preds:
                raise RuntimeError("audio model unavailable via hf_api")
        else:
            from app.services.model_loader import audio_classifier

            clf = audio_classifier()
            preds = clf(wav_path)
        if preds and isinstance(preds[0], list):
            preds = preds[0]
        scores = {p["label"].lower(): float(p["score"]) for p in preds}
        fake = max(
            (v for k, v in scores.items() if any(
                t in k for t in ("fake", "spoof", "synthetic", "deepfake", "label_1")
            )),
            default=0.0,
        )
        return Signal(
            name="audio_classifier",
            label="Signs this voice was synthetically generated"
            if fake >= 0.7 else "No strong sign of a synthetic voice",
            risk=round(fake, 3),
            direction="risk" if fake >= 0.7 else "neutral",
            detail="Automated voice-synthesis check (less reliable on noisy recordings).",
            raw={"scores": scores, "forensic": True},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("audio classifier unavailable: %s", exc)
        return Signal(
            name="audio_classifier", label="Automated voice check was unavailable",
            risk=0.25, direction="neutral", detail="Audio model could not load.",
            raw={"error": str(exc)[:120], "forensic": True},
        )


def _transcribe(wav_path: str) -> str:
    try:
        from app.services import inference

        if inference.use_hf_api():
            with open(wav_path, "rb") as f:
                return inference.transcribe(f.read()) or ""
        from app.services.model_loader import whisper_model

        model = whisper_model()
        segments, _ = model.transcribe(wav_path, beam_size=1)
        return " ".join(seg.text for seg in segments).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("transcription unavailable: %s", exc)
        return ""


def analyze(audio_bytes: bytes, suffix: str = ".ogg", db=None) -> ServiceOutput:
    from app.services import text as text_service

    signals: list[Signal] = []
    transcript = ""
    wav = _to_wav(audio_bytes, suffix)
    if wav:
        try:
            signals.append(_synthesis_signal(wav))
            transcript = _transcribe(wav)
        finally:
            try:
                os.unlink(wav)
            except OSError:
                pass
    else:
        signals.append(Signal(
            name="audio_decode", label="This audio could not be processed",
            risk=0.2, direction="neutral", detail="Audio could not be decoded.",
            raw={"forensic": True},
        ))

    sub_outputs = []
    if transcript:
        sub = text_service.analyze(transcript, db)
        sub_outputs.append(sub)
        signals.extend(sub.signals)

    return ServiceOutput(
        content_type=ContentType.audio,
        extracted_text=transcript or None,
        signals=signals,
        sub_outputs=sub_outputs,
        notes=["transcript captured" if transcript else "no speech transcribed"],
    )
