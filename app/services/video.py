"""Video service (brief §6).

Strategy: extract 5-8 keyframes spaced across the duration, run each through the
image classifier and aggregate; extract the audio track and run the full audio
pipeline; combine. We deliberately do NOT run full-video deep-learning inference
— it would OOM a free CPU Space. Keyframes + audio is a defensible engineering
choice, documented in the README.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from app.core.logging import get_logger
from app.schemas.analysis import ContentType, ServiceOutput, Signal

log = get_logger("video")

N_KEYFRAMES = 6


def _extract_keyframes(path: str) -> list[bytes]:
    try:
        import cv2

        cap = cv2.VideoCapture(path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if total <= 0:
            cap.release()
            return []
        idxs = [int(total * (i + 1) / (N_KEYFRAMES + 1)) for i in range(N_KEYFRAMES)]
        frames = []
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            ok, buf = cv2.imencode(".png", frame)
            if ok:
                frames.append(buf.tobytes())
        cap.release()
        return frames
    except Exception as exc:  # noqa: BLE001
        log.warning("keyframe extraction failed: %s", exc)
        return []


def _extract_audio(path: str) -> bytes | None:
    dst = path + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1", dst],
            check=True, capture_output=True, timeout=180,
        )
        with open(dst, "rb") as f:
            return f.read()
    except Exception as exc:  # noqa: BLE001
        log.info("audio track extraction failed: %s", exc)
        return None
    finally:
        try:
            os.unlink(dst)
        except OSError:
            pass


def analyze(video_bytes: bytes, suffix: str = ".mp4", db=None) -> ServiceOutput:
    from app.services import audio as audio_service
    from app.services import image as image_service

    src = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    src.write(video_bytes)
    src.close()

    signals: list[Signal] = []
    sub_outputs = []
    transcript = ""
    try:
        frames = _extract_keyframes(src.name)
        fake_scores = []
        for fb in frames:
            sig = image_service._classifier_signal(fb)  # noqa: SLF001
            fake_scores.append(sig.risk)
        if fake_scores:
            agg = sum(fake_scores) / len(fake_scores)
            peak = max(fake_scores)
            signals.append(Signal(
                name="video_frames",
                label="Signs the video's images were synthetically generated"
                if peak >= 0.7 else "No strong sign of synthetic video frames",
                risk=round(max(agg, peak * 0.9), 3),
                direction="risk" if peak >= 0.7 else "neutral",
                detail=f"Checked {len(frames)} frames across the video.",
                raw={"frame_scores": [round(s, 3) for s in fake_scores], "forensic": True},
            ))

        audio_bytes = _extract_audio(src.name)
        if audio_bytes:
            asub = audio_service.analyze(audio_bytes, ".wav", db)
            sub_outputs.append(asub)
            signals.extend(asub.signals)
            transcript = asub.extracted_text or ""
    finally:
        try:
            os.unlink(src.name)
        except OSError:
            pass

    return ServiceOutput(
        content_type=ContentType.video,
        extracted_text=transcript or None,
        signals=signals,
        sub_outputs=sub_outputs,
        notes=["keyframes + audio track analysed (no full-video inference)"],
    )
