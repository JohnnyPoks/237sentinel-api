"""SQLAlchemy models. Importing this package registers all mappers on Base."""
from app.models.tables import (  # noqa: F401
    Analysis,
    ApiKey,
    CommunityReport,
    Organization,
    OrgAlert,
    OrgChannel,
    ReportConfirmation,
    ScamPattern,
    UsageEvent,
)
