# Phase 4: adds pre_visit_attachments table.
from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.clinical.models


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0002_appointment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PreVisitAttachment",
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
                    "appointment",
                    models.ForeignKey(
                        db_column="appointment_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="clinical.appointment",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        db_column="uploaded_by_id",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_attachments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "file",
                    models.FileField(
                        upload_to=apps.clinical.models._attachment_upload_path,
                    ),
                ),
                (
                    "file_type",
                    models.CharField(
                        choices=[("pdf", "PDF"), ("jpeg", "JPEG"), ("png", "PNG")],
                        max_length=4,
                    ),
                ),
                ("original_filename", models.CharField(blank=True, default="", max_length=255)),
                ("file_size_bytes",   models.PositiveIntegerField(default=0)),
                ("uploaded_at",       models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "pre_visit_attachments"},
        ),
        migrations.AddIndex(
            model_name="previsitattachment",
            index=models.Index(
                fields=["appointment"], name="idx_attach_appointment"
            ),
        ),
    ]
