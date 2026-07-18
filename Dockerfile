# 237Sentinel API — Hugging Face Spaces (Docker SDK).
# CPU-only. Models load lazily at first request; the two primary-path models
# (link + text) are pre-fetched at build time so the first check is not slow.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/hf_cache \
    TRANSFORMERS_CACHE=/app/hf_cache \
    OMP_NUM_THREADS=2

# System deps: ffmpeg (audio/video), libGL + glib (opencv/easyocr runtime).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU torch first from the CPU wheel index (avoids the huge CUDA build),
# then the rest. torch is already satisfied so requirements won't refetch it.
RUN pip install --no-cache-dir torch==2.5.1 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-fetch the primary-path model weights into the image layer cache. Failure
# is non-fatal — the app still boots and fetches lazily on first use.
RUN python scripts/download_models.py || echo "model prefetch skipped"

# HF Spaces requires the app on port 7860.
EXPOSE 7860

# Spaces' filesystem is ephemeral; state lives in Postgres (DATABASE_URL).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
