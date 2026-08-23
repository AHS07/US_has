# Phase 6 — Notification, EmailJob, DoctorGoogleCredentials tables.
from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts",  "0001_initial"),
        ("clinical",  "0002_appointment"),   # Notification.appointment FK
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── Notification ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id",   models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("patient", models.ForeignKey(
                    db_column="patient_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="notifications",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("hospital", models.ForeignKey(
                    db_column="hospital_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="notifications",
                    to="accounts.hospital",
                )),
                ("appointment", models.ForeignKey(
                    blank=True, db_column="appointment_id", null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="notifications",
                    to="clinical.appointment",
                )),
                ("event_type", models.CharField(
                    choices=[
                        ("booking_confirmed",   "Booking confirmed"),
                        ("booking_cancelled",   "Booking cancelled"),
                        ("booking_rescheduled", "Booking rescheduled"),
                        ("doctor_absent",       "Doctor marked absent"),
                        ("reschedule_offer",    "Reschedule offered"),
                        ("running_late",        "Doctor running late"),
                        ("follow_up_available", "Follow-up available"),
                        ("visit_summary_ready", "Visit summary ready"),
                    ],
                    max_length=30,
                )),
                ("title",      models.CharField(max_length=200)),
                ("body",       models.TextField(blank=True, default="")),
                ("is_read",    models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "notifications", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["patient", "is_read"], name="idx_notif_patient_read"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["hospital", "event_type"], name="idx_notif_hospital_event"),
        ),

        # ── EmailJob ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="EmailJob",
            fields=[
                ("id",   models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("notification", models.OneToOneField(
                    db_column="notification_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="email_job",
                    to="notifications.notification",
                )),
                ("recipient_email", models.EmailField()),
                ("subject",         models.CharField(max_length=200)),
                ("body_text",       models.TextField()),
                ("body_html",       models.TextField(blank=True, default="")),
                ("ics_attachment",  models.TextField(blank=True, default="")),
                ("status",          models.CharField(
                    choices=[("pending","Pending"),("sent","Sent"),("failed","Failed"),("cancelled","Cancelled")],
                    db_index=True, default="pending", max_length=10,
                )),
                ("retry_count", models.PositiveSmallIntegerField(default=0)),
                ("last_error",  models.TextField(blank=True, default="")),
                ("sent_at",     models.DateTimeField(blank=True, null=True)),
                ("created_at",  models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "email_jobs"},
        ),
        migrations.AddIndex(
            model_name="emailjob",
            index=models.Index(fields=["status", "retry_count"], name="idx_emailjob_status"),
        ),

        # ── DoctorGoogleCredentials ───────────────────────────────────────────
        migrations.CreateModel(
            name="DoctorGoogleCredentials",
            fields=[
                ("id",   models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("doctor", models.OneToOneField(
                    db_column="doctor_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="google_credentials",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("access_token_enc",  models.TextField()),
                ("refresh_token_enc", models.TextField(blank=True, default="")),
                ("token_expiry",      models.DateTimeField(blank=True, null=True)),
                ("scopes",            models.TextField(blank=True, default="")),
                ("calendar_id",       models.CharField(blank=True, default="primary", max_length=200)),
                ("connected_at",      models.DateTimeField(auto_now_add=True)),
                ("updated_at",        models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "doctor_google_credentials"},
        ),
    ]
