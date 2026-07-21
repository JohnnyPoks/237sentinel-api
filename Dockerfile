# Default image = the free deployment (Render). No torch: the models run on
# Hugging Face and are called over HTTPS (INFERENCE_MODE=hf_api). ffmpeg is
# included so audio/video normalise before being sent to the hosted models.
# For the heavy in-process variant (HF PRO / local GPU-less), see Dockerfile.full.
#
# Non-secret config is baked in here so a plain Render web service works with no
# extra env vars — you only add the secret keys (HF_API_KEY, GEMINI_API_KEY,
# TELEGRAM_BOT_TOKEN) in the dashboard.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INFERENCE_MODE=hf_api \
    SEED_ON_STARTUP=true \
    LLM_PROVIDER=gemini,hf_router \
    LLM_MODEL=gemini-2.0-flash \
    APP_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-lite.txt .
RUN pip install --no-cache-dir -r requirements-lite.txt

COPY . .

# Render provides $PORT; default to 7860 for local runs.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
