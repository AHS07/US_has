"""
scheduling/models.py

Models: DoctorProfile, ShiftConfig, AppointmentSlot, DoctorLeave, DoctorAttendance

Design notes (from architecture.md / system-design doc):
- DoctorProfile is 1:1 with User(role=doctor); specialization, slot settings live here.
- ShiftConfig defines the doctor's weekly shift windows; slot generation reads from it.
- AppointmentSlot holds pre-generated batch slots (one row per hour-window per day).
  booked_count is the Postgres source of truth; Redis is a fast-path cache in front.
- DoctorLeave is whole-day planned leave set in advance.
- DoctorAttendance is day-of half-day granularity (morning/afternoon), defaults present
  (no row = present; a row only appears when someone marks absent).
"""
from __future__ import annotations

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class ShiftName(models.TextChoices):
    MORNING   = "morning",   "Morning"
    AFTERNOON = "afternoon", "Afternoon"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT  = "absent",  "Absent"


# ---------------------------------------------------------------------------
# DoctorProfile
# ---------------------------------------------------------------------------

class DoctorProfile(models.Model):
    """
    1:1 extension of User(role=doctor).
    Slot duration and capacity are admin-configurable per doctor.
    google_oauth_connected is a status flag only; the real credentials
    live in DoctorGoogleCredentials (Phase 6).
    """

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="doctor_profile",
        db_column="user_id",
    )
    specialization = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    google_oauth_connected = models.BooleanField(default=False)

    # Per-doctor slot settings (admin-configurable via PUT shift-config)
    slot_duration_minutes = models.PositiveSmallIntegerField(default=60)
    slot_capacity = models.PositiveSmallIntegerField(default=5)

    class Meta:
        db_table = "doctor_profiles"

    def __str__(self) -> str:
        return f"DoctorProfile({self.user_id})"


# ---------------------------------------------------------------------------
# ShiftConfig
# ---------------------------------------------------------------------------

class ShiftConfig(models.Model):
    """
    Working hours for a doctor.
    shift_1 = morning window (e.g. 09:00–13:00)
    shift_2 = afternoon window (e.g. 14:00–17:00)
    The 13:00–14:00 lunch gap is implicit — no slot is ever generated for it.
    working_days is a list of ISO weekday integers: 1=Mon … 7=Sun.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.OneToOneField(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="shift_config",
        db_column="doctor_id",
    )
    shift_1_start = models.TimeField(default="09:00")
    shift_1_end   = models.TimeField(default="13:00")
    shift_2_start = models.TimeField(default="14:00")
    shift_2_end   = models.TimeField(default="17:00")
    # ISO weekday numbers: [1,2,3,4,5] = Mon–Fri
    working_days  = ArrayField(
        models.PositiveSmallIntegerField(),
        default=list,
        size=7,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shift_configs"

    def __str__(self) -> str:
        return f"ShiftConfig({self.doctor_id})"


# ---------------------------------------------------------------------------
# AppointmentSlot
# ---------------------------------------------------------------------------

class AppointmentSlot(models.Model):
    """
    Pre-generated batch slot for one hour-window on one date.
    Capacity is snapshot of slot_capacity at generation time.
    booked_count is incremented under SELECT FOR UPDATE on confirm (Phase 3).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="slots",
        db_column="doctor_id",
    )
    # hospital_id is denormalized here so hospital-scoped queries are a simple filter
    hospital = models.ForeignKey(
        "accounts.Hospital",
        on_delete=models.CASCADE,
        related_name="appointment_slots",
        db_column="hospital_id",
    )
    date        = models.DateField()
    slot_start  = models.TimeField()
    slot_end    = models.TimeField()
    capacity    = models.PositiveSmallIntegerField()
    booked_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "appointment_slots"
        # Enforce uniqueness at DB level — no duplicate slots per doctor/date/time
        unique_together = [("doctor", "date", "slot_start")]
        indexes = [
            models.Index(fields=["doctor", "date"], name="idx_slots_doctor_date"),
            models.Index(fields=["hospital", "date"], name="idx_slots_hospital_date"),
        ]

    def __str__(self) -> str:
        return f"Slot({self.doctor_id} {self.date} {self.slot_start}–{self.slot_end})"

    @property
    def true_remaining(self) -> int:
        """Remaining capacity per Postgres (source of truth)."""
        return max(0, self.capacity - self.booked_count)


# ---------------------------------------------------------------------------
# DoctorLeave
# ---------------------------------------------------------------------------

class DoctorLeave(models.Model):
    """
    Whole-day planned leave set in advance by admin.
    Multiple leave rows per doctor are fine (one per leave date).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="leave_days",
        db_column="doctor_id",
    )
    date   = models.DateField()
    reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="leave_entries_created",
        db_column="created_by_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "doctor_leave"
        unique_together = [("doctor", "date")]
        indexes = [
            models.Index(fields=["doctor", "date"], name="idx_leave_doctor_date"),
        ]

    def __str__(self) -> str:
        return f"DoctorLeave({self.doctor_id} on {self.date})"


# ---------------------------------------------------------------------------
# DoctorAttendance
# ---------------------------------------------------------------------------

class DoctorAttendance(models.Model):
    """
    Day-of half-day attendance record.
    Only exists when a half-day is marked ABSENT — default is present.
    morning  = slots up to the clinic's lunch cutoff (shift_1)
    afternoon = slots after the lunch gap (shift_2)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        db_column="doctor_id",
    )
    date   = models.DateField()
    shift  = models.CharField(max_length=10, choices=ShiftName.choices)
    status = models.CharField(
        max_length=10,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.ABSENT,
    )
    marked_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="attendance_marks",
        db_column="marked_by_id",
    )
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "doctor_attendance"
        # One row per doctor/date/shift combination
        unique_together = [("doctor", "date", "shift")]
        indexes = [
            models.Index(fields=["doctor", "date"], name="idx_attendance_doctor_date"),
        ]

    def __str__(self) -> str:
        return f"Attendance({self.doctor_id} {self.date} {self.shift}: {self.status})"
