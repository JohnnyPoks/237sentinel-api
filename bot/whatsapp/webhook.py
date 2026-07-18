"""WhatsApp Business Cloud API webhook (scaffolded, disabled by default).

Provides a FastAPI router that can be mounted on the main app. Every endpoint is
inert unless `WHATSAPP_ENABLED=true`. The code is written to be correct against
the Cloud API (verification handshake, inbound message parsing, media download,
text reply) so it can be turned on once Business API approval is granted — but
we do NOT claim it works today.

To enable (after Meta approval):
  WHATSAPP_ENABLED=true
  WHATSAPP_TOKEN=<permanent access token>
  WHATSAPP_PHONE_NUMBER_ID=<from Meta>
  WHATSAPP_VERIFY_TOKEN=<a secret you choose; enter the same in Meta console>
Then mount this router in app/main.py and set the callback URL in Meta to
  https://<host>/whatsapp/webhook
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request, Response

from app.config import settings

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

GRAPH = "https://graph.facebook.com/v21.0"
API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:7860").rstrip("/")


def _enabled() -> bool:
    return settings.whatsapp_enabled and bool(settings.whatsapp_token)


@router.get("/webhook")
async def verify(request: Request) -> Response:
    """Meta verification handshake."""
    if not _enabled():
        return Response(status_code=404)
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.whatsapp_verify_token
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


async def _send_text(to: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{GRAPH}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body[:4000]},
            },
        )


async def _download_media(media_id: str) -> tuple[bytes, str] | None:
    async with httpx.AsyncClient(timeout=60) as client:
        meta = await client.get(
            f"{GRAPH}/{media_id}",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        )
        url = meta.json().get("url")
        if not url:
            return None
        blob = await client.get(
            url, headers={"Authorization": f"Bearer {settings.whatsapp_token}"}
        )
        return blob.content, meta.json().get("mime_type", "application/octet-stream")


def _format(result: dict) -> str:
    exp = result.get("explanation", {})
    badge = {"VERIFIED": "🟢", "UNCONFIRMED": "🟠", "ALTERED": "🔴"}.get(
        result.get("verdict", ""), "•"
    )
    return (
        f"{badge} {exp.get('headline_fr', '')}\n\n"
        f"{result.get('summary', '')}\n\n"
        f"{exp.get('body_fr', '')}\n\n"
        f"➡️ {exp.get('action_fr', '')}"
    )


@router.post("/webhook")
async def receive(request: Request) -> Response:
    if not _enabled():
        return Response(status_code=404)
    payload = await request.json()
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages", [])
        if not messages:
            return Response(status_code=200)
        msg = messages[0]
        sender = msg["from"]
        mtype = msg["type"]

        result = None
        async with httpx.AsyncClient(timeout=120) as client:
            if mtype == "text":
                r = await client.post(
                    f"{API_URL}/api/v1/analyze", json={"text": msg["text"]["body"]}
                )
                result = r.json()
            elif mtype in ("image", "audio", "video", "document"):
                media_id = msg[mtype]["id"]
                downloaded = await _download_media(media_id)
                if downloaded:
                    content, _mime = downloaded
                    r = await client.post(
                        f"{API_URL}/api/v1/analyze",
                        files={"file": (f"upload.{mtype}", content)},
                    )
                    result = r.json()

        if result:
            await _send_text(sender, _format(result))
        else:
            await _send_text(sender, "Envoyez-moi un message ou un fichier à vérifier.")
    except (KeyError, IndexError):
        pass  # ignore non-message webhooks (status callbacks, etc.)
    return Response(status_code=200)
