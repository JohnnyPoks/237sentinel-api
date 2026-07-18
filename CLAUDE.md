# CLAUDE.md — 237Sentinel API

Conventions, commands, and gotchas for future sessions working in this repo.

## Product rules that are not negotiable

1. **Never output "AI-generated" as a verdict.** AI-generated ≠ fraudulent. A
   shop's AI-made flyer is fine; a forged decree is not. The system answers *"is
   this what it claims to be, and from who it claims?"* — never *"was AI
   involved?"*. This rule is enforced in `services/explanation.py` and the
   semantic system prompt.
2. **Never overstate certainty.** Confidence is a band (low/medium/high), never a
   bare percentage in the citizen-facing payload. Say "we cannot confirm" when
   the evidence is thin. Do not put "99% accurate" anywhere.
3. **Not in the registry never means fake.** It means `UNCONFIRMED`. Enforced in
   `services/verification.py`; there is a test for it.
4. **Never invent a Hugging Face model ID.** Every ID lives in `config.Models`
   and was verified to exist. A 404 at model load is a demo-ending failure.
5. **Commits are plain and human.** No `Co-Authored-By`, no "Generated with…",
   no attribution trailers anywhere. Imperative mood.

## Commands

```bash
uvicorn app.main:app --reload --port 7860   # run dev server
python -m scripts.seed                       # seed registry + scam patterns (idempotent)
python -m scripts.download_models            # prefetch primary-path model weights
pytest                                       # unit tests (models mocked/absent)
pytest -m slow                               # integration tests that hit real models
```

## Architecture in one breath

`routers/analyze.py` → `services/router.py` (detect type) → the per-modality
service → `services/pipeline.py` orchestrates: gather signals + extracted text →
`services/semantic.py` (LLM: what is this about?) → `services/registry.py`
(is the sender registered?) → `services/verification.py` (→ one of three
verdicts) → `services/explanation.py` (plain EN/FR + action) → persist → return.

## Model loading gotchas

- **Never import torch/transformers at module top level.** All heavy imports are
  inside functions in `services/*.py` and `services/model_loader.py`. This lets
  the app boot (and the unit tests run) with those libraries absent, degrading to
  neutral "unavailable" signals. Do not break this.
- Models are **singletons, loaded on first use**, cached in `model_loader._cache`,
  with load times logged. Loading all models at import will OOM a free Space.
- On Linux/Spaces, install **CPU torch from the CPU wheel index** (see Dockerfile).
  PyPI `torch` on Linux pulls the multi-GB CUDA build.

## Degrade, never crash

Every sub-service wraps failures and returns a low-risk `neutral` signal instead
of raising. A WHOIS timeout, a failed model load, or a missing LLM key must never
fail the whole `/analyze` request. The LLM layer has a `none` provider that
triggers deterministic fallbacks in the semantic and explanation layers.

## Memory constraints (free CPU Space)

- Video: keyframes + audio only, never full-video inference.
- Whisper: `base` size, `int8` compute. Not `large`.
- Prefetch only link + text models at build; others fetch lazily.

## Config

All tunables live in `app/config.py`: `APP_NAME` (the one place the product is
named), `Models` (verified HF IDs), `Thresholds` (named, no magic numbers),
`TEXT_CANDIDATE_LABELS`. Change thresholds there, not inline in services.

## Database

SQLAlchemy 2.x. `DATABASE_URL` → Postgres in prod; SQLite fallback for local/first
run. `init_db()` (create_all) runs on startup for the fallback; Postgres should
use Alembic migrations. Never store raw IPs or full submissions.
