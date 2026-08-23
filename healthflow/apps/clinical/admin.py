"""clinical/admin.py — Phase 3 admin registrations."""
from django.contrib import admin

from apps.clinical.models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display  = ["id", "patient", "doctor", "slot", "status", "token", "pre_summary_status", "created_at"]
    list_filter   = ["status", "pre_summary_status"]
    search_fields = ["patient__email", "doctor__email"]
    ordering      = ["-created_at"]
    raw_id_fields = ["patient", "doctor", "slot", "hospital", "original_request"]
