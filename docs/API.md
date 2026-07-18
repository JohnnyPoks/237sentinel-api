# API

Base URL: `http://localhost:7860` locally, or your Space URL in production.
Interactive OpenAPI docs: `GET /api/v1/docs`.

All errors share one envelope: `{"error": {"code": "...", "message": "..."}}`.

## Analyze

### `POST /api/v1/analyze`

Accepts **JSON** (text / URL) or **multipart** (a file). The content router picks
the type — you never declare it.

```bash
# A pasted message
curl -s http://localhost:7860/api/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text": "URGENT: votre compte MTN sera bloqué. Envoyez votre code PIN pour valider avant 24h."}'

# A link
curl -s http://localhost:7860/api/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{"text": "https://www.minesec.gov.cm/communique"}'

# A file (image / audio / video / pdf) — type auto-detected
curl -s http://localhost:7860/api/v1/analyze \
  -F 'file=@suspicious.jpg' \
  -F 'consent_store=false'
```

Response (abridged):

```json
{
  "id": "…",
  "content_type": "text",
  "verdict": "UNCONFIRMED",
  "confidence": "low",
  "summary": "A payment message that asks for money and creates time pressure…",
  "semantic": { "financial_request": true, "urgency_pressure": true, "…": "…" },
  "registry": { "matched": false },
  "explanation": {
    "headline_en": "We cannot confirm this.",
    "headline_fr": "Nous ne pouvons pas le confirmer.",
    "body_en": "We found no proof this is fake, and no proof it is real. It asks you to pay…",
    "action_en": "Call them on a number you already have. Do not use the number in this message.",
    "checked_en": "We checked the writing."
  },
  "signals": [ { "name": "pattern:payment", "label": "Mobile Money PIN validation loop", "risk": 0.9, "direction": "risk" } ],
  "checked": ["text"]
}
```

### `GET /api/v1/analyze/{id}`

Retrieve a stored result by id.

## Registry

```bash
# Is this sender a registered official channel?
curl -s http://localhost:7860/api/v1/verify-sender \
  -H 'Content-Type: application/json' \
  -d '{"channel_type": "phone", "value": "8202"}'

# Search the public registry
curl -s "http://localhost:7860/api/v1/organizations?q=antic"

# Public organisation profile
curl -s http://localhost:7860/api/v1/organizations/antic

# Self-register (returns an API key once)
curl -s http://localhost:7860/api/v1/organizations \
  -H 'Content-Type: application/json' \
  -d '{"name": "École Bilingue X", "kind": "school", "channels": [{"channel_type": "phone", "value": "677123456"}]}'
```

## Organisation (authenticated — `X-API-Key`)

```bash
curl -s http://localhost:7860/api/v1/organizations/me/dashboard -H 'X-API-Key: sk_…'
curl -s http://localhost:7860/api/v1/organizations/me/alerts    -H 'X-API-Key: sk_…'
curl -s http://localhost:7860/api/v1/organizations/me/channels  -H 'X-API-Key: sk_…'
curl -s -X POST http://localhost:7860/api/v1/organizations/me/channels \
  -H 'X-API-Key: sk_…' -H 'Content-Type: application/json' \
  -d '{"channel_type": "domain", "value": "ecole-x.cm"}'
```

## Community reports

```bash
curl -s -X POST http://localhost:7860/api/v1/reports \
  -H 'Content-Type: application/json' \
  -d '{"category": "payment", "body": "Someone posing as my bank asked for my PIN."}'

curl -s "http://localhost:7860/api/v1/reports?limit=20"
curl -s -X POST http://localhost:7860/api/v1/reports/{id}/confirm
```

## Admin (authenticated — `X-Admin-Token`, disabled if `ADMIN_TOKEN` unset)

```bash
curl -s http://localhost:7860/api/v1/admin/stats -H 'X-Admin-Token: …'
curl -s http://localhost:7860/api/v1/admin/organizations/pending -H 'X-Admin-Token: …'
curl -s -X POST "http://localhost:7860/api/v1/admin/organizations/{id}/approve" -H 'X-Admin-Token: …'
```

## Public

```bash
curl -s http://localhost:7860/health
curl -s http://localhost:7860/api/v1/stats
```
