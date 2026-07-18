"""237Sentinel Telegram bot (brief §9).

Forward it anything — text, link, photo, voice note, video, document — and it
runs the same /api/v1/analyze pipeline and replies with the verdict in the same
plain wording as the website. Runs independently of the API process and is
env-gated: if TELEGRAM_BOT_TOKEN is absent it does nothing.

Run:  python -m bot.telegram_bot        (needs TELEGRAM_BOT_TOKEN set)

It talks to the API over HTTP (SENTINEL_API_URL, default http://localhost:7860)
so it works equally against a local server or the deployed Space.
"""
from __future__ import annotations

import os

import httpx

try:
    from telegram import (
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Update,
    )
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except Exception:  # noqa: BLE001 — library optional at import time
    Application = None  # type: ignore

API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:7860").rstrip("/")

# Per-chat language preference (en/fr). Defaults to fr for Cameroon.
_lang: dict[int, str] = {}

WELCOME = {
    "en": (
        "👋 I am 237Sentinel.\n\n"
        "Forward me anything suspicious — a message, a link, a photo, a voice "
        "note, a video or a PDF — and I will tell you whether to trust it, and "
        "why.\n\n"
        "Commands:\n"
        "/verify <name> — is an organisation registered?\n"
        "/report — report a scam to the community\n"
        "/lang — switch English / Français"
    ),
    "fr": (
        "👋 Je suis 237Sentinel.\n\n"
        "Transférez-moi tout ce qui vous semble suspect — un message, un lien, "
        "une photo, une note vocale, une vidéo ou un PDF — et je vous dirai s'il "
        "faut y faire confiance, et pourquoi.\n\n"
        "Commandes :\n"
        "/verify <nom> — une organisation est-elle enregistrée ?\n"
        "/report — signaler une arnaque à la communauté\n"
        "/lang — passer English / Français"
    ),
}


def _lang_of(chat_id: int) -> str:
    return _lang.get(chat_id, "fr")


def _format_result(result: dict, lang: str) -> str:
    exp = result.get("explanation", {})
    suffix = "fr" if lang == "fr" else "en"
    headline = exp.get(f"headline_{suffix}", "")
    body = exp.get(f"body_{suffix}", "")
    action = exp.get(f"action_{suffix}", "")
    checked = exp.get(f"checked_{suffix}", "")
    summary = result.get("summary", "")
    verdict = result.get("verdict", "")
    badge = {"VERIFIED": "🟢", "UNCONFIRMED": "🟠", "ALTERED": "🔴"}.get(verdict, "•")
    civic = (
        "Avant de partager, vérifiez la source."
        if lang == "fr"
        else "Before you share this, check the source."
    )
    return (
        f"{badge} *{headline}*\n\n"
        f"{summary}\n\n"
        f"{body}\n\n"
        f"_{checked}_\n\n"
        f"➡️ {action}\n\n"
        f"{civic}"
    )


async def _analyze_text(text: str) -> dict:
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{API_URL}/api/v1/analyze", json={"text": text})
        r.raise_for_status()
        return r.json()


async def _analyze_file(content: bytes, filename: str) -> dict:
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"{API_URL}/api/v1/analyze",
            files={"file": (filename, content)},
        )
        r.raise_for_status()
        return r.json()


def _me_too_markup(analysis_id: str) -> "InlineKeyboardMarkup":
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🙋 This happened to me too", callback_data=f"metoo:{analysis_id}")]]
    )


# --- Handlers --------------------------------------------------------------
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang_of(update.effective_chat.id)
    await update.message.reply_text(WELCOME[lang])


async def switch_lang(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    new = "en" if _lang_of(chat_id) == "fr" else "fr"
    _lang[chat_id] = new
    await update.message.reply_text(WELCOME[new])


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /verify <name>")
        return
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API_URL}/api/v1/organizations", params={"q": query})
        items = r.json().get("items", []) if r.status_code == 200 else []
    if not items:
        await update.message.reply_text("No registered organisation matches that name.")
        return
    lines = []
    for o in items[:5]:
        chans = ", ".join(c["value"] for c in o.get("channels", [])[:4])
        lines.append(f"✅ *{o['name']}*\n{chans or '—'}")
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def report_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "To report a scam, send me the message and I will analyse it — the result "
        "includes a button to add it to the community feed."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    lang = _lang_of(update.effective_chat.id)
    thinking = "Analyse en cours…" if lang == "fr" else "Checking…"
    await msg.reply_text(thinking)

    try:
        result = None
        file = None
        fname = "upload"
        if msg.photo:
            file, fname = await msg.photo[-1].get_file(), "photo.jpg"
        elif msg.voice:
            file, fname = await msg.voice.get_file(), "voice.ogg"
        elif msg.audio:
            file, fname = await msg.audio.get_file(), msg.audio.file_name or "audio.mp3"
        elif msg.video:
            file, fname = await msg.video.get_file(), "video.mp4"
        elif msg.document:
            file, fname = await msg.document.get_file(), msg.document.file_name or "doc.pdf"

        if file is not None:
            content = bytes(await file.download_as_bytearray())
            result = await _analyze_file(content, fname)
        elif msg.text:
            result = await _analyze_text(msg.text)
        else:
            await msg.reply_text("Send me a message, link or file to check.")
            return

        await msg.reply_text(
            _format_result(result, lang),
            parse_mode="Markdown",
            reply_markup=_me_too_markup(result["id"]),
        )
    except Exception:  # noqa: BLE001
        err = "Une erreur est survenue. Réessayez." if lang == "fr" else "Something went wrong. Please try again."
        await msg.reply_text(err)


async def on_me_too(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    analysis_id = q.data.split(":", 1)[1]
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{API_URL}/api/v1/reports",
            json={
                "category": "other",
                "body": "Reported via Telegram: this happened to me too.",
                "linked_analysis_id": analysis_id,
            },
        )
    await q.edit_message_reply_markup(reply_markup=None)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or Application is None:
        print("TELEGRAM_BOT_TOKEN not set (or python-telegram-bot missing); bot disabled.")
        return
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", switch_lang))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CallbackQueryHandler(on_me_too, pattern=r"^metoo:"))
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO
            | filters.VIDEO | filters.Document.ALL,
            handle_message,
        )
    )
    print(f"237Sentinel Telegram bot running, API at {API_URL}")
    app.run_polling()


if __name__ == "__main__":
    main()
