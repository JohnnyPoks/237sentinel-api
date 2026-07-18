# DECISIONS.md — 237Sentinel API

A running log of meaningful choices and why. Newest at the bottom of each section.

## Architecture

- **Provider-agnostic LLM with a first-class `none` provider.** `services/llm.py`
  exposes one `complete()` primitive over Anthropic / OpenAI-compatible / HF
  Inference backends. `none` returns a sentinel so the semantic and explanation
  layers use deterministic rule-based logic. Why: the whole app must run with
  zero API keys (the default) and the demo must never die because a key is
  missing or a provider is rate-limited.
- **Semantic + explanation layers separated from `llm.py`.** The brief suggested a
  single `analyze()` in `llm.py`; instead `llm.py` is the transport and
  `semantic.py`/`explanation.py` own the prompts and parsing. Cleaner, and the
  brief's real intent (provider-agnostic, swappable, callers unaware of backend)
  is preserved.
- **Signals are a common currency.** Every service emits `Signal(name, label,
  risk 0..1, direction)`. The verification engine aggregates uniformly and never
  needs to know which service produced a signal. `direction` (risk/trust/neutral)
  means "domain is 8 years old" is never mistaken for a risk.
- **Verdict logic centralised, thresholds named.** All cut-offs live in
  `config.Thresholds`. ELA is weighted down (0.35 vs 0.65 for DL classifiers) and
  a lone high-ELA reading can never produce ALTERED — ELA is unreliable alone on
  re-encoded images. There are tests for this.
- **`UNCONFIRMED` is the deliberate default.** Encoded directly: only a positive
  registry match yields VERIFIED; only strong forensic evidence yields ALTERED;
  everything else is UNCONFIRMED. Not-in-registry is never "fake".

## Data / privacy

- **No raw IPs, ever.** A per-process salted hash is used for rate limiting and
  "me too" dedupe. Analyses store a redacted 180-char preview, not the full
  submission. Media stored only with explicit consent, purged at 30 days. Maps to
  Law No. 2024/017.
- **In-memory rate limiting.** Fine for a single Space instance and the demo; a
  multi-instance deployment should move it to Redis. Documented in the README.

## Seed data (the honesty-sensitive part)

- **Only verified public channels are seeded, and the set is deliberately small.**
  Registry matches drive the VERIFIED verdict, so a wrong "official" channel is
  actively harmful (it could bless a scammer or fail to match the real sender).
  Every channel in `scripts/seed.py` was checked against the organisation's own
  website or a public reporting shortcode at build time (ANTIC 8202/8206 and
  cirt.cm; MTN care 8787 and mtn.cm; Orange care 950 and orange.cm; the
  `*.gov.cm` ministry domains; etc.). Corrected during build: MTN care is **8787**
  not 8888, Orange is **950**, MINSANTE is **minsante.gov.cm** not minsante.cm.
- **Phone numbers beyond published shortcodes were left out.** We did not invent
  customer-service landlines. A production deployment must re-confirm every
  channel directly with the organisation before relying on it. All seeds are
  `source=public_record, verified_by=seed` — they are public information, not
  customers.

## Admin

- **Single admin token, disabled by default.** `/api/v1/admin` requires
  `X-Admin-Token == ADMIN_TOKEN`; if `ADMIN_TOKEN` is unset every admin endpoint
  returns 401. A real deployment should front this with a proper identity
  provider. Chosen for shippability without adding an auth stack.

## Deployment

- **CPU torch from the PyTorch CPU wheel index** in the Dockerfile — PyPI torch on
  Linux is the multi-GB CUDA build and would blow the image size and cold start.
- **Prefetch only link + text models at build.** Prefetching every model (mDeBERTa
  alone is ~560 MB, plus image/audio/whisper/OCR) would bloat the image and risk a
  build timeout. The primary path is fast on first call; media modalities fetch
  lazily. Documented as a trade-off in docs/MODELS.md.

## Open items / needs from the maintainer

- A Postgres `DATABASE_URL` (Supabase/Neon) for production persistence.
- An LLM key (Anthropic recommended) to move the semantic/explanation layers off
  the deterministic fallback — the fallback is solid but an LLM sharpens the
  "what does this content want?" reading.
- Per-organisation confirmation before expanding the registry seed.
