"""237Sentinel API entrypoint.

Wires logging, CORS, error handling, and routers. Models are NOT loaded here —
they load lazily on first use so the app boots fast and a free Space does not
OOM at startup. The interactive OpenAPI docs are served at /api/v1/docs.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import APP_NAME, APP_TAGLINE, settings
from app.core.errors import SentinelError, sentinel_error_handler
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.routers import admin, analyze, health, organizations, reports

configure_logging()
log = get_logger("main")

app = FastAPI(
    title=f"{APP_NAME} API",
    description=(
        f"{APP_TAGLINE}\n\n"
        "A digital verification platform for Cameroon. Send it anything "
        "suspicious — a link, message, image, voice note, video or PDF — and it "
        "tells you whether to trust it, and why, in plain language.\n\n"
        "This service answers *is this what it claims to be, and is it from who "
        "it claims to be from?* — never *was AI involved?*"
    ),
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url=None,
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https://.*\.web\.app|https://.*\.firebaseapp\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(SentinelError, sentinel_error_handler)

app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(organizations.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    # Ensure tables exist for the SQLite fallback / first run. Postgres uses
    # Alembic; create_all is a no-op where migrations already ran.
    try:
        init_db()
        log.info("database ready (%s)", settings.effective_database_url.split("://")[0])
    except Exception as exc:  # noqa: BLE001
        log.error("database init failed: %s", exc)

    if settings.seed_on_startup:
        try:
            from scripts.seed import seed

            seed()
        except Exception as exc:  # noqa: BLE001
            log.error("startup seed failed: %s", exc)


@app.get("/")
def root() -> dict:
    return {
        "app": APP_NAME,
        "tagline": APP_TAGLINE,
        "docs": "/api/v1/docs",
        "health": "/health",
    }
