"""Development settings — never use in production."""
from .base import *  # noqa: F401, F403

DEBUG = True

# Looser hosts in dev
ALLOWED_HOSTS = ["*"]

# Use console email backend in dev — no SMTP server needed
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Use SQLite for local dev/CI when Postgres is not running.
# Docker Compose still uses Postgres — this only applies outside Docker.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405  (BASE_DIR from base.py)
    }
}

# django-debug-toolbar (only if installed — guard so Phase 0 works before full install)
try:
    import debug_toolbar  # noqa: F401

    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1"]
except ImportError:
    pass
