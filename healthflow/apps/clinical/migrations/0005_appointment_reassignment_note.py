# Phase 7: adds reassignment_note to Appointment.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0004_consultation"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="reassignment_note",
            field=models.TextField(blank=True, default=""),
        ),
    ]
