# Architecture

## The pipeline, step by step

A submission enters at `POST /api/v1/analyze` and flows through:

1. **Content router** (`services/router.py`) — detects the type from the MIME
   type / extension (files) or shape (a bare URL is a link; anything else is
   text). The user never declares the type.

2. **Per-modality service** — one of `link`, `text`, `image`, `audio`, `video`,
   `document`. Each returns a `ServiceOutput` with:
   - `extracted_text` — transcript / OCR / pasted text,
   - `signals` — a flat list of `Signal(name, label, risk 0..1, direction)`,
   - `sub_outputs` — nested results (e.g. a video's audio → its transcript → text
     signals), preserved for the audit trail.

   Services fan out: audio transcribes then calls text; image OCRs then calls
   text; video extracts keyframes (→ image) and the audio track (→ audio);
   document extracts text (→ text) and embedded images (→ image, for the
   pasted-stamp check).

3. **Semantic layer** (`services/semantic.py`) — the core. Sends the gathered
   text + a summary of forensic findings to the LLM under a strict JSON contract
   (`SemanticResult`): what is this content, who does it claim to be, what does it
   ask the person to do, is there a financial request / urgency / identity claim.
   Retries once on bad JSON, then falls back to a deterministic heuristic pass. It
   answers *"what is happening?"*, never *"was AI involved?"*.

4. **Registry lookup** (`services/registry.py`) — extracts sender identifiers
   (phones, handles, domains) from the text, normalises them, and checks them
   against registered official channels. A match means "this is really them".

5. **Verification engine** (`services/verification.py`) — combines the signals,
   the semantic reading, and the registry match into exactly one verdict:
   - **ALTERED** if there is strong forensic evidence of synthesis/alteration
     (and never on ELA alone).
   - **VERIFIED** if a registry match and no strong manipulation.
   - **UNCONFIRMED** otherwise — the honest default.
   Confidence is a band derived from how many independent signals agree.

6. **Explanation layer** (`services/explanation.py`) — turns the outcome into
   plain EN/FR: a headline, what happened, one clear action, a civic line, and a
   human "what we checked" sentence. No jargon, never "AI-generated".

7. **Persist + respond** — a redacted analysis row is stored; the full
   `AnalysisResult` is returned. If the content claimed a known organisation but
   matched no channel, an impersonation alert is raised for that organisation.

## Why the semantic layer matters

Wrong output: *"Video: 87% deepfake probability."*

Right output: *"This video shows someone presenting themselves as an official of
MINESEC, announcing a scholarship and asking viewers to send 15,000 FCFA to
register. We found signs the face was synthetically generated. MINESEC has no
registered channel matching this account. Do not send money."*

The forensic classifiers answer "was this manipulated?". The semantic layer
answers "what is happening, who is it claiming to be, and what does it want?".
Both go into the verdict. Neither is sufficient alone.

## Deliberate engineering trade-offs

- **Video = keyframes + audio, not full-video inference.** We extract 6 keyframes
  spaced across the duration, run each through the image classifier and aggregate
  (peak-weighted), and run the audio track through the full audio pipeline. Full
  temporal deep-learning inference would OOM a free CPU Space. This is a defensible
  choice, not a shortcut.
- **Lazy, singleton model loading.** Nothing heavy loads at import; each model
  loads on first use and is cached. A free Space cannot hold every model in memory
  at once at startup.
- **Graceful degradation everywhere.** Any failing signal becomes a low-risk
  `neutral` signal. The request always returns a verdict.

## Data model

`analyses`, `organizations`, `org_channels`, `org_alerts`, `community_reports`,
`report_confirmations`, `scam_patterns`, `api_keys`, `usage_events`. See
`app/models/tables.py`. Personal identifiers are kept out of anything that feeds
the pattern layer or the community feed.
