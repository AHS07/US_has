# This makes the Celery app available as the default app for the Django project,
# so that shared_task decorator works correctly across all apps.
from .celery import app as celery_app

__all__ = ("celery_app",)
