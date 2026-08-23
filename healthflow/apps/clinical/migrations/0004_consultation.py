# Phase 5: MedicineCatalog, VisitNote, Prescription; Appointment Phase 5 fields.
from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clinical",  "0003_pre_visit_attachment"),
        ("accounts",  "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── MedicineCatalog ──────────────────────────────────────────────────
        migrations.CreateModel(
            name="MedicineCatalog",
            fields=[
                ("id",   models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("hospital", models.ForeignKey(
                    db_column="hospital_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="medicine_catalog",
                    to="accounts.hospital",
                )),
                ("name",           models.CharField(max_length=200)),
                ("generic_name",   models.CharField(blank=True, default="", max_length=200)),
                ("default_dosage", models.CharField(blank=True, default="", max_length=100)),
                ("status",         models.CharField(
                    choices=[("active","Active"),("pending_review","Pending review"),("rejected","Rejected")],
                    db_index=True, default="active", max_length=15,
                )),
                ("created_by", models.ForeignKey(
                    db_column="created_by_id", null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="medicines_created",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "medicine_catalog"},
        ),
        migrations.AddIndex(
            model_name="medicinecatalog",
            index=models.Index(fields=["hospital","status"], name="idx_med_hospital_status"),
        ),
        migrations.AddIndex(
            model_name="medicinecatalog",
            index=models.Index(fields=["hospital","name"], name="idx_med_hospital_name"),
        ),

        # ── Appointment Phase 5 fields ───────────────────────────────────────
        migrations.AddField(
            model_name="appointment",
            name="summary_status",
            field=models.CharField(
                choices=[("pending","Pending"),("draft","Draft"),("approved","Approved"),("unavailable","Unavailable")],
                db_index=True, default="pending", max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="appointment",
            name="post_summary_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="appointment",
            name="approved_by",
            field=models.ForeignKey(
                blank=True, db_column="approved_by_id", null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_summaries",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="appointment",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appointment",
            name="follow_up_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),

        # ── VisitNote ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="VisitNote",
            fields=[
                ("id",  models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("appointment", models.OneToOneField(
                    db_column="appointment_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="visit_note",
                    to="clinical.appointment",
                )),
                ("notes", models.TextField()),
                ("created_by", models.ForeignKey(
                    db_column="created_by_id", null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="visit_notes_authored",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "visit_notes"},
        ),

        # ── Prescription ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Prescription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("appointment", models.ForeignKey(
                    db_column="appointment_id",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="prescriptions",
                    to="clinical.appointment",
                )),
                ("medicine", models.ForeignKey(
                    db_column="medicine_id",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="prescriptions",
                    to="clinical.medicinecatalog",
                )),
                ("dosage",       models.CharField(max_length=100)),
                ("frequency",    models.CharField(
                    choices=[
                        ("once_daily","Once daily"),("twice_daily","Twice daily"),
                        ("three_times_daily","Three times daily"),("four_times_daily","Four times daily"),
                        ("at_bedtime","At bedtime"),("as_needed","As needed"),
                    ],
                    max_length=20,
                )),
                ("duration",     models.CharField(max_length=50)),
                ("instructions", models.TextField(blank=True, default="")),
                ("sort_order",   models.PositiveSmallIntegerField(default=0)),
                ("created_at",   models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "prescriptions", "ordering": ["sort_order", "created_at"]},
        ),
        migrations.AddIndex(
            model_name="prescription",
            index=models.Index(fields=["appointment"], name="idx_rx_appointment"),
        ),
    ]
