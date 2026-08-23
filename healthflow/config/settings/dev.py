"""Development settings — never use in production."""
from .base import *  # noqa: F401, F403

DEBUG = True

# Looser hosts in dev
ALLOWED_HOSTS = ["*"]

# Use console email backend in dev — no SMTP server needed
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# By default in dev, use PostgreSQL configured in base.py (connected via .env).
# Fall back to SQLite only if USE_SQLITE is explicitly enabled.
if config("USE_SQLITE", cast=bool, default=False):  # noqa: F405
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
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
