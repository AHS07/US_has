# Phase 3: drops Phase 1 PatientNote fixture, creates Appointment table.
from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0001_initial"),
        ("accounts", "0001_initial"),
        ("scheduling", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Drop Phase 1 fixture ─────────────────────────────────────────────
        migrations.DeleteModel(name="PatientNote"),

        # ── Create Appointment ───────────────────────────────────────────────
        migrations.CreateModel(
            name="Appointment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        db_column="patient_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "doctor",
                    models.ForeignKey(
                        db_column="doctor_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="doctor_appointments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "slot",
                    models.ForeignKey(
                        db_column="slot_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="scheduling.appointmentslot",
                    ),
                ),
                (
                    "hospital",
                    models.ForeignKey(
                        db_column="hospital_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="accounts.hospital",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("held",       "Held"),
                            ("confirmed",  "Confirmed"),
                            ("completed",  "Completed"),
                            ("cancelled",  "Cancelled"),
                            ("no_show",    "No Show"),
                            ("reassigned", "Reassigned"),
                        ],
                        default="held",
                        db_index=True,
                        max_length=12,
                    ),
                ),
                (
                    "cancel_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("patient_initiated",  "Patient initiated"),
                            ("affected_by_leave",  "Affected by leave"),
                            ("affected_by_absent", "Affected by absence"),
                        ],
                        default="",
                        max_length=20,
                    ),
                ),
                ("held_until",          models.DateTimeField(blank=True, null=True)),
                ("token",               models.PositiveSmallIntegerField(blank=True, null=True)),
                ("symptom_text",        models.TextField(blank=True, default="")),
                ("urgency_level",       models.CharField(blank=True, default="", max_length=6)),
                ("ai_pre_summary_id",   models.CharField(blank=True, default="", max_length=64)),
                (
                    "pre_summary_status",
                    models.CharField(
                        choices=[
                            ("pending",     "Pending"),
                            ("ready",       "Ready"),
                            ("unavailable", "Unavailable"),
                        ],
                        default="pending",
                        max_length=12,
                    ),
                ),
                (
                    "original_request",
                    models.ForeignKey(
                        blank=True,
                        db_column="original_request_id",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reassignments",
                        to="clinical.appointment",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "appointments"},
        ),

        # ── Indexes ──────────────────────────────────────────────────────────
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["patient", "status"], name="idx_appt_patient_status"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["doctor", "status"], name="idx_appt_doctor_status"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["hospital", "status"], name="idx_appt_hospital_status"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["slot", "status"], name="idx_appt_slot_status"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["held_until"], name="idx_appt_held_until"),
        ),
    ]
