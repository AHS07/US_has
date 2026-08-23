"""Celery application instance for HealthFlow."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("healthflow")

# Load config from Django settings, using the CELERY_ namespace prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all installed apps.
app.autodiscover_tasks()


# ---------------------------------------------------------------------------
# Celery Beat schedule
# All times are UTC. Adjust crontab() hours to match the clinic's timezone
# offset when deploying to production.
# ---------------------------------------------------------------------------

app.conf.beat_schedule = {

    # ── Slot generation — nightly, rolling 30-day window ─────────────────────
    # This fires the per-doctor task via a management-style approach;
    # the actual per-doctor dispatch happens inside the task itself.
    # Runs at 01:00 UTC every night so slots are ready before clinic opens.
    "nightly-slot-generation": {
        "task":     "scheduling.nightly_slot_generation",
        "schedule": crontab(hour=1, minute=0),
    },

    # ── Redis counter reconciliation — every hour ─────────────────────────────
    "hourly-reconcile-slot-counters": {
        "task":     "scheduling.reconcile_slot_counters",
        "schedule": crontab(minute=0),   # top of every hour
    },

    # ── Expire stale holds — every 5 minutes ─────────────────────────────────
    # Holds expire after SLOT_HOLD_TTL_SECONDS (default 600 s).
    # Running every 5 min means max 5 min of capacity leak after a hold times out.
    "expire-stale-holds": {
        "task":     "notifications.expire_stale_holds",
        "schedule": crontab(minute="*/5"),
    },

    # ── No-show sweep — every 30 minutes ─────────────────────────────────────
    # Confirmed appointments past their slot window → no_show.
    "no-show-sweep": {
        "task":     "notifications.no_show_sweep",
        "schedule": crontab(minute="*/30"),
    },

    # ── Running-late check — every 15 minutes during clinic hours ─────────────
    # Clinic hours assumed 07:00–18:00 UTC (adjust per deployment).
    "running-late-check": {
        "task":     "notifications.running_late_check",
        "schedule": crontab(minute="*/15", hour="7-18"),
    },

    # ── Medication / follow-up reminder dispatch — daily at 08:00 UTC ─────────
    "daily-medication-reminder": {
        "task":     "notifications.medication_reminder_dispatch",
        "schedule": crontab(hour=8, minute=0),
    },
}


# ---------------------------------------------------------------------------
# Nightly slot generation — fan-out task
# ---------------------------------------------------------------------------

@app.task(name="scheduling.nightly_slot_generation", ignore_result=False)
def nightly_slot_generation() -> dict:
    """
    Enqueue slot_generation_task for every active doctor, rolling 30-day window
    from tomorrow.  Runs nightly at 01:00 UTC.

    Uses .delay() so each doctor's generation runs independently and failures
    are isolated.
    """
    import datetime
    from apps.scheduling.models import DoctorProfile
    from apps.scheduling.tasks import slot_generation_task

    today      = datetime.date.today()
    date_from  = (today + datetime.timedelta(days=1)).isoformat()
    date_to    = (today + datetime.timedelta(days=30)).isoformat()

    doctors  = DoctorProfile.objects.filter(is_active=True).values_list("user_id", flat=True)
    enqueued = 0

    for doctor_user_id in doctors:
        slot_generation_task.delay(str(doctor_user_id), date_from, date_to)
        enqueued += 1

    import logging
    logging.getLogger(__name__).info(
        "nightly_slot_generation: enqueued %d doctors (%s – %s)", enqueued, date_from, date_to
    )
    return {"status": "ok", "enqueued": enqueued, "date_from": date_from, "date_to": date_to}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
