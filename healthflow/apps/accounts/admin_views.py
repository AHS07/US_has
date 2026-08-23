"""
accounts/admin_views.py

Admin portal endpoints: hospital bootstrap, admin/doctor/patient creation,
doctor and patient listing.

Rules:
- Every write creates accounts with must_reset_password=True
- Temp passwords are generated with secrets.token_urlsafe, emailed, never returned in response
- Admin endpoints scope all queries by hospital_id — no unscoped patient-data queries
"""
from __future__ import annotations

import secrets

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Hospital, User, UserRole
from apps.accounts.permissions import IsAdmin, IsNotForcedReset
from apps.accounts.serializers import (
    CreateAdminSerializer,
    CreateDoctorSerializer,
    CreatePatientSerializer,
    HospitalBootstrapSerializer,
    UserProfileSerializer,
    _make_token_pair,
)
from apps.accounts.views import _send_temp_password_email

# ─── Hospital bootstrap ───────────────────────────────────────────────────────

class HospitalBootstrapView(APIView):
    """
    POST /admin/hospitals
    Registers the very first hospital + its first admin.
    Returns a token pair so the admin is immediately logged in.
    Blocked if any hospital already exists.
    """
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        if Hospital.objects.exists():
            return Response(
                {"error": {"code": "forbidden", "message": "Hospital already registered."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = HospitalBootstrapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        with transaction.atomic():
            hospital = Hospital.objects.create(
                name=d["hospital_name"],
                address=d.get("hospital_address", ""),
                contact_email=d["contact_email"],
            )
            admin = User.objects.create_superuser(
                email=d["admin_email"],
                password=d["admin_password"],
                name=d["admin_name"],
                role=UserRole.ADMIN,
                hospital=hospital,
                must_reset_password=False,  # bootstrap admin sets their own password directly
            )

        tokens = _make_token_pair(admin)
        return Response(
            {
                **tokens,
                "must_reset_password": False,
                "role": UserRole.ADMIN,
                "hospital_id": str(hospital.id),
            },
            status=status.HTTP_201_CREATED,
        )


# ─── Admin management ─────────────────────────────────────────────────────────

class AdminListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        admins = User.objects.filter(
            role=UserRole.ADMIN, hospital=request.user.hospital
        ).order_by("name")
        return Response(UserProfileSerializer(admins, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = CreateAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        temp_password = secrets.token_urlsafe(12)
        with transaction.atomic():
            new_admin = User.objects.create_user(
                email=d["email"],
                password=temp_password,
                name=d["name"],
                role=UserRole.ADMIN,
                hospital=request.user.hospital,
                phone=d.get("phone", ""),
                must_reset_password=True,
                created_by=request.user,
            )

        _send_temp_password_email(new_admin, temp_password)
        return Response(UserProfileSerializer(new_admin).data, status=status.HTTP_201_CREATED)


# ─── Doctor management ────────────────────────────────────────────────────────

class DoctorListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        from apps.scheduling.models import DoctorProfile
        from apps.scheduling.serializers import DoctorProfileSerializer

        profiles = DoctorProfile.objects.select_related(
            "user", "shift_config"
        ).filter(
            user__hospital=request.user.hospital,
        ).order_by("user__name")

        search = request.query_params.get("search", "").strip()
        if search:
            profiles = profiles.filter(user__name__icontains=search)

        return Response(DoctorProfileSerializer(profiles, many=True).data)

    def post(self, request: Request) -> Response:
        from apps.scheduling.models import DoctorProfile, ShiftConfig

        serializer = CreateDoctorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        temp_password = secrets.token_urlsafe(12)
        with transaction.atomic():
            doctor = User.objects.create_user(
                email=d["email"],
                password=temp_password,
                name=d["name"],
                role=UserRole.DOCTOR,
                hospital=request.user.hospital,
                phone=d.get("phone", ""),
                must_reset_password=True,
                created_by=request.user,
            )
            # Phase 2: create DoctorProfile + default ShiftConfig in the same transaction
            profile = DoctorProfile.objects.create(
                user=doctor,
                specialization=d["specialization"],
            )
            ShiftConfig.objects.create(
                doctor=profile,
                working_days=[1, 2, 3, 4, 5],  # Mon–Fri default
            )

        _send_temp_password_email(doctor, temp_password)
        from apps.scheduling.serializers import DoctorProfileSerializer
        profile.refresh_from_db()
        return Response(DoctorProfileSerializer(profile).data, status=status.HTTP_201_CREATED)


class DoctorDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request, doctor_id: str) -> Response:
        doctor = _get_hospital_doctor(request, doctor_id)
        return Response(UserProfileSerializer(doctor).data)

    def patch(self, request: Request, doctor_id: str) -> Response:
        doctor = _get_hospital_doctor(request, doctor_id)
        # name/phone live on User; specialization/is_active live on DoctorProfile (Phase 2)
        for field in ("name", "phone"):
            if field in request.data:
                setattr(doctor, field, request.data[field])
        doctor.save(update_fields=["name", "phone"])
        return Response(UserProfileSerializer(doctor).data)


# ─── Patient management ───────────────────────────────────────────────────────

class PatientListCreateView(APIView):
    """
    GET  /admin/patients  — patients who have at least one appointment at this hospital.
                            In Phase 1 (no appointments yet) returns empty list.
    POST /admin/patients  — create a patient account, send temp password.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        from apps.clinical.models import Appointment, AppointmentStatus
        from django.db.models import Count, Max

        search = request.query_params.get("search", "").strip()

        # Patients who have at least one appointment at this hospital
        patient_ids = (
            Appointment.objects
            .filter(hospital=request.user.hospital)
            .values_list("patient_id", flat=True)
            .distinct()
        )

        patients = User.objects.filter(
            id__in=patient_ids,
            role=UserRole.PATIENT,
        ).order_by("name")

        if search:
            patients = patients.filter(name__icontains=search)

        # Annotate with appointment count + most-recent appointment date
        # using a separate query to keep this simple and scoped
        result = []
        for patient in patients:
            appt_qs = Appointment.objects.filter(
                patient=patient, hospital=request.user.hospital
            )
            total = appt_qs.count()
            latest = appt_qs.order_by("-slot__date").select_related("slot").first()
            result.append({
                **UserProfileSerializer(patient).data,
                "appointment_count":    total,
                "last_appointment_date": latest.slot.date.isoformat() if latest else None,
                "last_appointment_status": latest.status if latest else None,
            })

        return Response(result)

    def post(self, request: Request) -> Response:
        serializer = CreatePatientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        temp_password = secrets.token_urlsafe(12)
        with transaction.atomic():
            patient = User.objects.create_user(
                email=d["email"],
                password=temp_password,
                name=d["name"],
                role=UserRole.PATIENT,
                hospital=None,  # patients are hospital-agnostic
                phone=d.get("phone", ""),
                must_reset_password=True,
                created_by=request.user,
            )

        _send_temp_password_email(patient, temp_password)
        return Response(UserProfileSerializer(patient).data, status=status.HTTP_201_CREATED)


class PatientDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def patch(self, request: Request, patient_id: str) -> Response:
        # Only permitted if the patient has an appointment at this admin's hospital (Phase 3).
        # In Phase 1 allow edit of any patient the admin created at their hospital.
        try:
            patient = User.objects.get(id=patient_id, role=UserRole.PATIENT,
                                       created_by__hospital=request.user.hospital)
        except User.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Patient not found.") from None
        for field in ("name", "phone"):
            if field in request.data:
                setattr(patient, field, request.data[field])
        patient.save(update_fields=["name", "phone"])
        return Response(UserProfileSerializer(patient).data)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_hospital_doctor(request: Request, doctor_id: str) -> User:
    from rest_framework.exceptions import NotFound
    try:
        return User.objects.get(
            id=doctor_id, role=UserRole.DOCTOR, hospital=request.user.hospital
        )
    except User.DoesNotExist:
        raise NotFound("Doctor not found.") from None


# ─── Dashboard (Phase 9) ──────────────────────────────────────────────────────

class DashboardStatsView(APIView):
    """
    GET /admin-api/dashboard

    Hospital-scoped aggregate stats for the admin portal home screen.
    All queries are scoped to request.user.hospital — never cross-hospital.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        from datetime import date
        from apps.clinical.models import Appointment, AppointmentStatus, MedicineCatalog, MedicineStatus
        from apps.notifications.models import Notification
        from apps.scheduling.models import DoctorProfile

        hospital = request.user.hospital
        today    = date.today()

        # Doctors active at this hospital
        doctor_count = DoctorProfile.objects.filter(
            user__hospital=hospital, is_active=True
        ).count()

        # Today's confirmed + completed bookings
        todays_bookings = Appointment.objects.filter(
            hospital=hospital,
            slot__date=today,
            status__in=[AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED],
        ).count()

        # Pending-review medicines in this hospital's catalog
        pending_medicines = MedicineCatalog.objects.filter(
            hospital=hospital,
            status=MedicineStatus.PENDING_REVIEW,
        ).count()

        # Unread notifications for all patients at this hospital
        # (proxy: notifications belonging to this hospital)
        unread_notifications = Notification.objects.filter(
            hospital=hospital,
            is_read=False,
        ).count()

        # Today's recent appointments (last 10) for the activity list
        recent = (
            Appointment.objects
            .filter(hospital=hospital, slot__date=today)
            .select_related("patient", "doctor", "slot")
            .order_by("-slot__slot_start")[:10]
        )
        recent_list = [
            {
                "appointment_id": str(a.id),
                "patient_name":   a.patient.name,
                "doctor_name":    a.doctor.name,
                "slot_start":     a.slot.slot_start.strftime("%H:%M"),
                "status":         a.status,
                "token":          a.token,
            }
            for a in recent
        ]

        return Response({
            "date":                today.isoformat(),
            "doctor_count":        doctor_count,
            "todays_bookings":     todays_bookings,
            "pending_medicines":   pending_medicines,
            "unread_notifications": unread_notifications,
            "recent_appointments": recent_list,
        })
