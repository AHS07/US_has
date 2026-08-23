"""
scheduling/admin.py

Django admin registrations for scheduling models.
Gives superusers visibility into scheduling data via /django-admin/.
"""
from django.contrib import admin

from apps.scheduling.models import (
    AppointmentSlot,
    DoctorAttendance,
    DoctorLeave,
    DoctorProfile,
    ShiftConfig,
)


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display   = ["user", "specialization", "is_active", "slot_duration_minutes", "slot_capacity"]
    list_filter    = ["is_active", "specialization"]
    search_fields  = ["user__name", "user__email", "specialization"]
    raw_id_fields  = ["user"]


@admin.register(ShiftConfig)
class ShiftConfigAdmin(admin.ModelAdmin):
    list_display  = ["doctor", "shift_1_start", "shift_1_end", "shift_2_start", "shift_2_end", "working_days", "updated_at"]
    raw_id_fields = ["doctor"]


@admin.register(AppointmentSlot)
class AppointmentSlotAdmin(admin.ModelAdmin):
    list_display  = ["doctor", "hospital", "date", "slot_start", "slot_end", "capacity", "booked_count"]
    list_filter   = ["date", "hospital"]
    search_fields = ["doctor__user__name"]
    ordering      = ["date", "slot_start"]


@admin.register(DoctorLeave)
class DoctorLeaveAdmin(admin.ModelAdmin):
    list_display  = ["doctor", "date", "reason", "created_by", "created_at"]
    list_filter   = ["date"]
    search_fields = ["doctor__user__name"]
    ordering      = ["date"]


@admin.register(DoctorAttendance)
class DoctorAttendanceAdmin(admin.ModelAdmin):
    list_display  = ["doctor", "date", "shift", "status", "marked_by", "marked_at"]
    list_filter   = ["date", "shift", "status"]
    search_fields = ["doctor__user__name"]
    ordering      = ["date", "shift"]
