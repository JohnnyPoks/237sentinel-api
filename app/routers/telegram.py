"""Telegram bot as a webhook (brief §9), hosted inside the API web service.

Running the bot as a webhook (instead of long-polling) means it lives in the same
Render web service — no separate worker process, and the bot token stays a
server-side secret (TELEGRAM_BOT_TOKEN), never in the repo or the browser.

Set-up (done once the service is live):
  POST https://api.telegram.org/bot<token>/setWebhook
       ?url=https://<host>/telegram/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>

Every endpoint is inert if TELEGRAM_BOT_TOKEN is unset.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, Request, Response

from app.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.schemas.analysis import ContentType
from app.services import pipeline, registry as registry_service, router as content_router

log = get_logger("telegram")

router = APIRouter(prefix="/telegram", tags=["telegram"])

API = "https://api.telegram.org"

WELCOME = {
    "en": (
        "👋 I am 237Sentinel.\n\nForward me anything suspicious — a message, a "
        "link, a photo, a voice note, a video or a PDF — and I will tell you "
        "whether to trust it, and why.\n\n/verify <name> — is an organisation "
        "registered?"
    ),
    "fr": (
        "👋 Je suis 237Sentinel.\n\nTransférez-moi tout ce qui vous semble "
        "suspect — un message, un lien, une photo, une note vocale, une vidéo "
        "ou un PDF — et je vous dirai s'il faut y faire confiance, et pourquoi."
        "\n\n/verify <nom> — une organisation est-elle enregistrée ?"
    ),
}

_BADGE = {"VERIFIED": "🟢", "UNCONFIRMED": "🟠", "ALTERED": "🔴"}


def _enabled() -> bool:
    return bool(settings.telegram_bot_token)


def _lang(update_msg: dict) -> str:
    code = (update_msg.get("from", {}) or {}).get("language_code", "") or ""
    return "en" if code.startswith("en") else "fr"


def _send(chat_id: int, text: str) -> None:
    try:
        httpx.post(
            f"{API}/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "Markdown"},
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram send failed: %s", exc)


def _download(file_id: str) -> tuple[bytes, str] | None:
    try:
        meta = httpx.get(
            f"{API}/bot{settings.telegram_bot_token}/getFile",
            params={"file_id": file_id}, timeout=20,
        ).json()
        path = meta["result"]["file_path"]
        blob = httpx.get(
            f"{API}/file/bot{settings.telegram_bot_token}/{path}", timeout=60
        ).content
        return blob, path
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram download failed: %s", exc)
        return None


def _format(result: dict, lang: str) -> str:
    exp = result.get("explanation", {})
    s = "fr" if lang == "fr" else "en"
    badge = _BADGE.get(result.get("verdict", ""), "•")
    civic = (
        "Avant de partager, vérifiez la source."
        if lang == "fr" else "Before you share this, check the source."
    )
    return (
        f"{badge} *{exp.get(f'headline_{s}', '')}*\n\n"
        f"{result.get('summary', '')}\n\n"
        f"{exp.get(f'body_{s}', '')}\n\n"
        f"_{exp.get(f'checked_{s}', '')}_\n\n"
        f"➡️ {exp.get(f'action_{s}', '')}\n\n{civic}"
    )


def _process(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    lang = _lang(msg)
    text = msg.get("text", "") or msg.get("caption", "")

    # Commands
    if text.startswith("/start") or text.startswith("/help"):
        _send(chat_id, WELCOME[lang])
        return
    if text.startswith("/verify"):
        q = text[len("/verify"):].strip()
        db = SessionLocal()
        try:
            m = registry_service.match_any(db, q) if q else None
            hit = registry_service.lookup(db, "domain", q) if q and "." in q else None
            found = m if (m and m.matched) else hit
            if found and found.matched:
                _send(chat_id, f"✅ *{found.organization_name}* is registered.")
            else:
                _send(chat_id, "No registered organisation matches that." if lang == "en"
                      else "Aucune organisation enregistrée ne correspond.")
        finally:
            db.close()
        return

    _send(chat_id, "Analyse en cours…" if lang == "fr" else "Checking…")

    file_bytes = None
    suffix = ""
    kind = None
    try:
        if msg.get("photo"):
            got = _download(msg["photo"][-1]["file_id"])
            if got:
                file_bytes, suffix = got[0], ".jpg"
                kind = ContentType.image
        elif msg.get("voice"):
            got = _download(msg["voice"]["file_id"])
            if got:
                file_bytes, suffix = got[0], ".ogg"
                kind = ContentType.audio
        elif msg.get("audio"):
            got = _download(msg["audio"]["file_id"])
            if got:
                file_bytes, suffix = got[0], ".mp3"
                kind = ContentType.audio
        elif msg.get("video"):
            got = _download(msg["video"]["file_id"])
            if got:
                file_bytes, suffix = got[0], ".mp4"
                kind = ContentType.video
        elif msg.get("document"):
            got = _download(msg["document"]["file_id"])
            if got:
                name = msg["document"].get("file_name", "doc.pdf")
                file_bytes = got[0]
                suffix = name[name.rfind("."):] if "." in name else ".pdf"
                kind = content_router.detect_from_file(name, None)
        elif text:
            kind = content_router.detect_from_text(text)

        if kind is None:
            _send(chat_id, "Send me a message, link or file to check." if lang == "en"
                  else "Envoyez-moi un message, un lien ou un fichier à vérifier.")
            return

        db = SessionLocal()
        try:
            result = pipeline.run(
                db, kind, text=text or None, file_bytes=file_bytes, suffix=suffix
            ).model_dump()
        finally:
            db.close()
        _send(chat_id, _format(result, lang))
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram processing failed: %s", exc)
        _send(chat_id, "Une erreur est survenue. Réessayez." if lang == "fr"
              else "Something went wrong. Please try again.")


@router.get("/webhook")
def webhook_health() -> dict:
    return {"telegram": "enabled" if _enabled() else "disabled"}


@router.post("/webhook")
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    if not _enabled():
        return Response(status_code=200)
    # Verify the secret token if one is configured (set via setWebhook).
    secret = settings.telegram_webhook_secret
    if secret and x_telegram_bot_api_secret_token != secret:
        return Response(status_code=403)
    update = await request.json()
    # Acknowledge immediately; analysis (which calls hosted models) runs after.
    background.add_task(_process, update)
    return Response(status_code=200)
