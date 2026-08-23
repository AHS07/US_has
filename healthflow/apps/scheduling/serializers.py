"""
scheduling/serializers.py

Serializers for Phase 2 admin scheduling endpoints.
Validation lives here; views orchestrate; business logic stays in services.py.
"""
from __future__ import annotations

import datetime
from typing import Any

from rest_framework import serializers

from apps.scheduling.models import (
    AppointmentSlot,
    AttendanceStatus,
    DoctorAttendance,
    DoctorLeave,
    DoctorProfile,
    ShiftConfig,
    ShiftName,
)


# ---------------------------------------------------------------------------
# DoctorProfile / ShiftConfig
# ---------------------------------------------------------------------------

class ShiftConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftConfig
        fields = [
            "shift_1_start", "shift_1_end",
            "shift_2_start", "shift_2_end",
            "working_days",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate_working_days(self, value: list[int]) -> list[int]:
        if not value:
            raise serializers.ValidationError("At least one working day is required.")
        for d in value:
            if d not in range(1, 8):
                raise serializers.ValidationError(
                    f"Invalid weekday {d!r}. Use ISO weekday integers 1 (Mon) – 7 (Sun)."
                )
        return sorted(set(value))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        s1_start = attrs.get("shift_1_start", self.instance.shift_1_start if self.instance else None)
        s1_end   = attrs.get("shift_1_end",   self.instance.shift_1_end   if self.instance else None)
        s2_start = attrs.get("shift_2_start", self.instance.shift_2_start if self.instance else None)
        s2_end   = attrs.get("shift_2_end",   self.instance.shift_2_end   if self.instance else None)

        if s1_start and s1_end and s1_start >= s1_end:
            raise serializers.ValidationError(
                {"shift_1_end": "Shift 1 end must be after shift 1 start."}
            )
        if s2_start and s2_end and s2_start >= s2_end:
            raise serializers.ValidationError(
                {"shift_2_end": "Shift 2 end must be after shift 2 start."}
            )
        if s1_end and s2_start and s1_end > s2_start:
            raise serializers.ValidationError(
                {"shift_2_start": "Shift 2 must start after shift 1 ends."}
            )
        return attrs


class DoctorProfileSerializer(serializers.ModelSerializer):
    """Read serializer — includes nested shift_config if present."""
    user_id        = serializers.UUIDField(source="user.id", read_only=True)
    name           = serializers.CharField(source="user.name", read_only=True)
    email          = serializers.EmailField(source="user.email", read_only=True)
    phone          = serializers.CharField(source="user.phone", read_only=True)
    hospital_id    = serializers.UUIDField(source="user.hospital_id", read_only=True)
    shift_config   = ShiftConfigSerializer(read_only=True)

    class Meta:
        model = DoctorProfile
        fields = [
            "user_id", "name", "email", "phone", "hospital_id",
            "specialization", "is_active",
            "slot_duration_minutes", "slot_capacity",
            "google_oauth_connected",
            "shift_config",
        ]


class ShiftConfigUpdateSerializer(serializers.Serializer):
    """
    PUT /admin-api/doctors/<id>/shift-config
    Updates ShiftConfig + slot settings on DoctorProfile in one call.
    """
    shift_1_start         = serializers.TimeField()
    shift_1_end           = serializers.TimeField()
    shift_2_start         = serializers.TimeField()
    shift_2_end           = serializers.TimeField()
    working_days          = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=7),
        min_length=1,
    )
    slot_duration_minutes = serializers.IntegerField(min_value=15, max_value=240)
    slot_capacity         = serializers.IntegerField(min_value=1, max_value=50)

    def validate_working_days(self, value: list[int]) -> list[int]:
        return sorted(set(value))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["shift_1_start"] >= attrs["shift_1_end"]:
            raise serializers.ValidationError(
                {"shift_1_end": "Shift 1 end must be after shift 1 start."}
            )
        if attrs["shift_2_start"] >= attrs["shift_2_end"]:
            raise serializers.ValidationError(
                {"shift_2_end": "Shift 2 end must be after shift 2 start."}
            )
        if attrs["shift_1_end"] > attrs["shift_2_start"]:
            raise serializers.ValidationError(
                {"shift_2_start": "Shift 2 must start after shift 1 ends."}
            )
        return attrs


class DoctorProfileUpdateSerializer(serializers.Serializer):
    """PATCH /admin-api/doctors/<id> — edit active status and specialization."""
    specialization = serializers.CharField(max_length=100, required=False)
    is_active      = serializers.BooleanField(required=False)


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

class DoctorLeaveSerializer(serializers.ModelSerializer):
    doctor_id  = serializers.UUIDField(source="doctor.user_id", read_only=True)
    created_by = serializers.UUIDField(source="created_by_id", read_only=True)

    class Meta:
        model = DoctorLeave
        fields = ["id", "doctor_id", "date", "reason", "created_by", "created_at"]
        read_only_fields = ["id", "doctor_id", "created_by", "created_at"]


class CreateLeaveSerializer(serializers.Serializer):
    """POST /admin-api/doctors/<id>/leave"""
    date   = serializers.DateField()
    reason = serializers.CharField(required=False, default="", allow_blank=True)

    def validate_date(self, value: datetime.date) -> datetime.date:
        if value < datetime.date.today():
            raise serializers.ValidationError("Leave date cannot be in the past.")
        return value


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

class DoctorAttendanceSerializer(serializers.ModelSerializer):
    doctor_id = serializers.UUIDField(source="doctor.user_id", read_only=True)
    marked_by = serializers.UUIDField(source="marked_by_id", read_only=True)

    class Meta:
        model = DoctorAttendance
        fields = ["id", "doctor_id", "date", "shift", "status", "marked_by", "marked_at"]
        read_only_fields = ["id", "doctor_id", "marked_by", "marked_at"]


class AttendanceUpdateSerializer(serializers.Serializer):
    """PUT /admin-api/attendance/<doctor_id>"""
    date   = serializers.DateField()
    shift  = serializers.ChoiceField(choices=ShiftName.choices)
    status = serializers.ChoiceField(choices=AttendanceStatus.choices)


class AttendanceSheetEntrySerializer(serializers.Serializer):
    """
    One row in the GET /admin-api/attendance?date= response.
    Represents a doctor + their two half-day statuses for that date.
    """
    doctor_id          = serializers.UUIDField()
    name               = serializers.CharField()
    specialization     = serializers.CharField()
    shifts             = serializers.CharField()   # human-readable "09:00–13:00 / 14:00–17:00"
    morning_status     = serializers.CharField()   # "present" | "absent" | "on_leave"
    afternoon_status   = serializers.CharField()
    on_leave           = serializers.BooleanField()


# ---------------------------------------------------------------------------
# Slot generation
# ---------------------------------------------------------------------------

class SlotGenerateSerializer(serializers.Serializer):
    """POST /admin-api/doctors/<id>/slots/generate"""
    date_from = serializers.DateField()
    date_to   = serializers.DateField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError(
                {"date_to": "date_to must be on or after date_from."}
            )
        delta = (attrs["date_to"] - attrs["date_from"]).days
        if delta > 365:
            raise serializers.ValidationError(
                {"date_to": "Generation window cannot exceed 365 days."}
            )
        return attrs


class AppointmentSlotSerializer(serializers.ModelSerializer):
    true_remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = AppointmentSlot
        fields = [
            "id", "doctor_id", "hospital_id",
            "date", "slot_start", "slot_end",
            "capacity", "booked_count", "true_remaining",
        ]
