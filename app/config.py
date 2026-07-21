"""Central configuration for the 237Sentinel API.

Every tunable lives here. Verification thresholds are named constants, never
magic numbers scattered across services. The product name lives in exactly one
place (`APP_NAME`) so it can be rebranded in a single line — it is provisional.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- The one place the product is named. Change here to rebrand. -------------
APP_NAME = "237Sentinel"
APP_TAGLINE = "You send us something. We tell you if it's real, and why."


# --- Verified Hugging Face model IDs. Do not substitute without verifying. ---
# A 404 at model-load time is a demo-ending failure. Each ID below was given as
# verified in the build brief; see docs/MODELS.md for benchmarks and limits.
class Models:
    LINK = "CrabInHoney/urlbert-tiny-v4-malicious-url-classifier"
    LINK_FALLBACK = "CrabInHoney/urlbert-tiny-v4-phishing-classifier"
    TEXT_ZEROSHOT = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    AUDIO = "MelodyMachine/Deepfake-audio-detection-V2"
    AUDIO_FALLBACK = "mo-thecreator/Deepfake-audio-detection"
    IMAGE = "Wvolf/ViT_Deepfake_Detection"
    IMAGE_ALT = "prithivMLmods/deepfake-detector-model-v1"
    WHISPER = "base"  # faster-whisper size; not "large" — memory on free Space


# --- Zero-shot candidate labels for the text service (brief §6). -------------
TEXT_CANDIDATE_LABELS = [
    "monetary demand",
    "urgency",
    "account suspension",
    "investment offer",
    "prize or lottery",
    "recruitment offer",
    "identity claim",
    "credential request",
]


class Thresholds:
    """Named weights and cut-offs for the verification engine.

    Signals are aggregated on a 0..1 risk scale. These decide the band an
    individual signal lands in; the engine (services/verification.py) combines
    them. Tuned conservatively: we would rather say UNCONFIRMED than cry ALTERED.
    """

    # A forensic manipulation score at/above this is "strong evidence".
    ALTERED_STRONG = 0.80
    # Below this, a manipulation signal is treated as noise, not evidence.
    ALTERED_IGNORE_BELOW = 0.55

    # Domain age (days) under which registration is a strong risk signal.
    DOMAIN_AGE_RISK_DAYS = 30

    # Link classifier: phishing/malware probability that counts as risky.
    LINK_RISK = 0.60

    # Zero-shot label score that counts as "this label is present".
    TEXT_LABEL_PRESENT = 0.65

    # ELA is deliberately down-weighted — unreliable alone on re-encoded images.
    ELA_WEIGHT = 0.35
    # Deep-learning image/audio classifiers carry more weight than ELA.
    CLASSIFIER_WEIGHT = 0.65

    # Confidence bands: how much corroborating evidence we require.
    # Number of independent signals pointing the same way for each band.
    CONF_HIGH_SIGNALS = 3
    CONF_MEDIUM_SIGNALS = 2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = ""

    llm_provider: str = "none"  # gemini | anthropic | openai | hf | none
    llm_model: str = "gemini-2.0-flash"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    hf_api_key: str = ""

    hf_home: str = "./hf_cache"
    hf_token: str = ""

    # How model inference runs:
    #   local  -> load transformers/torch models in-process (needs a big host)
    #   hf_api -> call the models hosted on Hugging Face over HTTPS (light host,
    #             e.g. Render free tier). Needs HF_API_KEY. This is how the free
    #             deployment leverages the open-source models without shipping torch.
    inference_mode: str = "local"

    google_safe_browsing_key: str = ""

    rate_limit_per_hour: int = 20
    rate_limit_video_per_hour: int = 5

    store_media: bool = False
    media_retention_days: int = 30

    # Simple admin gate for the moderation endpoints (X-Admin-Token header).
    admin_token: str = ""

    # Re-seed the registry + scam patterns on startup. Useful on hosts with an
    # ephemeral filesystem (Render free tier + SQLite), where seed data would
    # otherwise be lost on restart. Idempotent.
    seed_on_startup: bool = False

    telegram_bot_token: str = ""

    whatsapp_enabled: bool = False
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_database_url(self) -> str:
        """Fall back to a local SQLite file so the app boots without Postgres.

        Production must set DATABASE_URL to Postgres — the Space filesystem is
        ephemeral, so SQLite there loses data on restart. Documented in README.
        """
        if self.database_url:
            return self.database_url
        return "sqlite:///./local.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
