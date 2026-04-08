import os


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


DATABASE_URL = _env("DATABASE_URL", "postgresql://hr:hr@localhost:5432/hr_service")
TELEGRAM_SYNC_INTERVAL_SECONDS = int(_env("TELEGRAM_SYNC_INTERVAL_SECONDS", "300") or "300")
TELEGRAM_QUEUED_POLL_SECONDS = int(_env("TELEGRAM_QUEUED_POLL_SECONDS", "15") or "15")
TELEGRAM_SYNC_ENABLED = _env("TELEGRAM_SYNC_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
TELEGRAM_SYNC_BATCH_SIZE = int(_env("TELEGRAM_SYNC_BATCH_SIZE", "100") or "100")
SECRET_KEY = _env("SECRET_KEY", "change-me")
TOKEN_ENCRYPTION_KEY = _env("TOKEN_ENCRYPTION_KEY", "")
TELEGRAM_SESSION_ENCRYPTION_KEY = _env("TELEGRAM_SESSION_ENCRYPTION_KEY", "")
TELEGRAM_RESUME_CLASSIFIER_MIN_SCORE = float(
    _env("TELEGRAM_RESUME_CLASSIFIER_MIN_SCORE", "0.6") or "0.6"
)
TELEGRAM_RESUME_CLASSIFIER_ENABLED = _env(
    "TELEGRAM_RESUME_CLASSIFIER_ENABLED", "true"
).lower() in ("1", "true", "yes")
TELEGRAM_ATTACHMENTS_DIR = _env("TELEGRAM_ATTACHMENTS_DIR", "/data/attachments")
TELEGRAM_MAX_ATTACHMENT_MB = int(_env("TELEGRAM_MAX_ATTACHMENT_MB", "10") or "10")
_allowed = _env("TELEGRAM_ALLOWED_ATTACHMENT_TYPES", "pdf,docx,doc,txt")
TELEGRAM_ALLOWED_ATTACHMENT_EXTS: frozenset[str] = frozenset(
    x.strip().lower() for x in _allowed.split(",") if x.strip()
)
TELEGRAM_MAX_ATTACHMENT_BYTES = max(1, TELEGRAM_MAX_ATTACHMENT_MB) * 1024 * 1024
