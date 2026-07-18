# Bots

## Telegram (live)

A working Telegram bot. Forward it anything — text, link, photo, voice note,
video, document — and it runs the same `/api/v1/analyze` pipeline and replies
with the verdict in the same plain wording as the website. `/verify <name>`
looks up the registry; an inline "this happened to me too" button files a
community report.

```bash
export TELEGRAM_BOT_TOKEN=...          # from @BotFather
export SENTINEL_API_URL=http://localhost:7860   # or the deployed Space URL
python -m bot.telegram_bot
```

It is env-gated: without `TELEGRAM_BOT_TOKEN`, the API and everything else run
normally and the bot simply does not start.

## WhatsApp (scaffolded, NOT live)

`bot/whatsapp/` is a complete, correct integration against the **WhatsApp
Business Cloud API** — but it is **disabled by default and not claimed to work**.
It requires Meta Business API approval and a verified phone number, which we do
not have. The code exists so it can be switched on once approval is granted:

1. Get WhatsApp Business Cloud API access and a permanent token from Meta.
2. Set `WHATSAPP_ENABLED=true`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_VERIFY_TOKEN`.
3. Mount the router in `app/main.py`:
   ```python
   from bot.whatsapp.webhook import router as whatsapp_router
   app.include_router(whatsapp_router)
   ```
4. In the Meta console set the callback URL to `https://<host>/whatsapp/webhook`
   and the verify token to the same value as `WHATSAPP_VERIFY_TOKEN`.

Until then every WhatsApp endpoint returns 404.
