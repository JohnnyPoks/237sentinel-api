# 237Sentinel — API

> **You send us something. We tell you if it's real, and why.**

Backend for [237Sentinel](https://sentinel237cm.web.app), a digital verification
platform for Cameroon. A citizen sends anything suspicious — a link, message,
image, voice note, video or PDF — and it answers, in plain EN/FR, whether to
trust it and what to do next. It asks *"is this what it claims to be, and from
who it claims?"* — **never** *"was AI involved?"*.

- **Live site:** https://sentinel237cm.web.app
- **Live API + docs:** https://two37sentinel-api.onrender.com/api/v1/docs
- **Frontend repo:** https://github.com/JohnnyPoks/237sentinel-web

## The three verdicts

| Verdict | Meaning | When |
|---|---|---|
| **VERIFIED** | "This is really them." | Sender matches a registered official channel, no strong manipulation. |
| **UNCONFIRMED** | "We cannot confirm this." | Not in the registry, no strong evidence either way. The honest, most common default — *not-in-registry never means fake*. |
| **ALTERED** | "This was altered." | Strong forensic evidence of synthesis/alteration. |

## How it works

`POST /api/v1/analyze` → content router detects the type → per-modality service
(link / text / image / audio / video / document) → **semantic layer** (what is
this, who does it claim to be, what does it want?) → registry lookup → the
verification engine picks one verdict → plain-language EN/FR explanation.

The models run on **Hugging Face** (called over HTTPS) and the reasoning uses a
fallback chain **Gemini → HF router (Llama-3.3-70B / Llama-4 vision) →
rule-based**, so the backend stays light and never hard-fails. Details:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/MODELS.md](docs/MODELS.md) ·
[docs/API.md](docs/API.md).

## Run locally

Python 3.11 (3.10 works too).

```bash
python -m venv .venv && source .venv/Scripts/activate   # .venv/bin/activate on mac/linux
pip install -r requirements.txt
cp .env.example .env          # runs with zero keys (rule-based fallback + SQLite)
python -m scripts.seed        # seed the registry + scam patterns
uvicorn app.main:app --reload --port 7860
```

Open http://localhost:7860/api/v1/docs. Set keys in `.env` to enable the models
(`HF_API_KEY`) and the LLM chain (`GEMINI_API_KEY`).

## Deploy — Render (free, default)

The default [`Dockerfile`](Dockerfile) is the light image (no torch): models run
on Hugging Face via `INFERENCE_MODE=hf_api`. Render → **New → Blueprint** (reads
[`render.yaml`](render.yaml)) or a plain Docker web service. Set the secrets
`HF_API_KEY`, `GEMINI_API_KEY`, and `TELEGRAM_BOT_TOKEN` in the dashboard;
everything else is baked into the image. The registry re-seeds on startup
(ephemeral disk); set `DATABASE_URL` (Supabase/Neon) for durable data.

The heavy in-process image (local `torch`) is [`Dockerfile.full`](Dockerfile.full),
for a large host / HF PRO.

## Bots

Telegram runs as a webhook inside this service ([`bot/`](bot) has a polling
variant too); WhatsApp is scaffolded but disabled. See [bot/README.md](bot/README.md).

## Data protection

No raw IPs (salted hashes only); a short redacted preview is stored, never the
full submission; media only with consent, purged at 30 days. Maps to Law
No. 2024/017.

## Current limitations

EN/FR only (no Pidgin/Camfranglais); no SIM-swap check; WhatsApp not live; field
accuracy is lower than lab benchmarks — results are guidance, not proof. See
[docs/MODELS.md](docs/MODELS.md).

## License

MIT — see [LICENSE](LICENSE).
