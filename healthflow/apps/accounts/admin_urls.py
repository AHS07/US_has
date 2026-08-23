"""Admin portal routes — /admin-api/..."""
from django.urls import path

from apps.accounts.admin_views import (
    AdminListCreateView,
    DoctorDetailView,
    DoctorListCreateView,
    HospitalBootstrapView,
    PatientDetailView,
    PatientListCreateView,
)
from apps.scheduling.views import (
    AttendanceMarkView,
    AttendanceSheetView,
    DoctorLeaveDetailView,
    DoctorLeaveListView,
    DoctorProfileDetailView,
    ShiftConfigView,
    SlotGenerateView,
)

app_name = "admin_api"

urlpatterns = [
    # Hospital bootstrap — public, only works when no hospital exists yet
    path("hospitals", HospitalBootstrapView.as_view(), name="hospital-bootstrap"),

    # Admin management
    path("admins", AdminListCreateView.as_view(), name="admin-list-create"),

    # ── Doctor management ─────────────────────────────────────────────────
    # Phase 1: basic user CRUD (create, list, patch name/phone)
    path("doctors", DoctorListCreateView.as_view(), name="doctor-list-create"),
    path("doctors/<uuid:doctor_id>", DoctorDetailView.as_view(), name="doctor-detail"),

    # Phase 2: scheduling profile + shift config
    path(
        "doctors/<uuid:doctor_id>/profile",
        DoctorProfileDetailView.as_view(),
        name="doctor-profile",
    ),
    path(
        "doctors/<uuid:doctor_id>/shift-config",
        ShiftConfigView.as_view(),
        name="doctor-shift-config",
    ),

    # Phase 2: leave CRUD
    path(
        "doctors/<uuid:doctor_id>/leave",
        DoctorLeaveListView.as_view(),
        name="doctor-leave-list",
    ),
    path(
        "doctors/<uuid:doctor_id>/leave/<uuid:leave_id>",
        DoctorLeaveDetailView.as_view(),
        name="doctor-leave-detail",
    ),

    # Phase 2: slot generation (on-demand)
    path(
        "doctors/<uuid:doctor_id>/slots/generate",
        SlotGenerateView.as_view(),
        name="slot-generate",
    ),

    # ── Attendance ────────────────────────────────────────────────────────
    path("attendance", AttendanceSheetView.as_view(), name="attendance-sheet"),
    path(
        "attendance/<uuid:doctor_id>",
        AttendanceMarkView.as_view(),
        name="attendance-mark",
    ),

    # ── Patient management ────────────────────────────────────────────────
    path("patients", PatientListCreateView.as_view(), name="patient-list-create"),
    path("patients/<uuid:patient_id>", PatientDetailView.as_view(), name="patient-detail"),
]
