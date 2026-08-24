"""
clinical/urls.py — Phase 3 booking + Phase 4 attachments + Phase 5 consultation.
Mounted at "" in config/urls.py.

Patient booking:
  POST   /appointments/hold
  POST   /appointments/:id/confirm
  DELETE /appointments/:id/hold
  POST   /appointments/:id/cancel
  POST   /appointments/:id/reschedule
  GET    /appointments/me
  GET    /appointments/:id
  GET    /appointments/:id/post-visit-summary   ← Phase 5

Attachments (Phase 4):
  GET/POST /appointments/:id/attachments
  DELETE   /appointments/:id/attachments/:att_id

Doctor-facing (Phase 3/5):
  GET    /doctor/appointments/:id
  POST   /doctor/appointments/:id/consultation   ← Phase 5
  GET    /doctor/appointments/:id/summary        ← Phase 5
  PUT    /doctor/appointments/:id/summary/approve ← Phase 5

Patient discovery:
  GET    /doctors
  GET    /doctors/:id/slots

Medicine catalog (Phase 5):
  GET    /medicine-catalog
  POST   /medicine-catalog
  PATCH  /medicine-catalog/:id
"""
from django.urls import path

from apps.clinical.views import (
    AppointmentDetailView,
    AppointmentListView,
    AttachmentDeleteView,
    AttachmentDownloadView,
    AttachmentListCreateView,
    CancelHoldView,
    CancelView,
    ConfirmView,
    ConsultationView,
    DoctorAppointmentDetailView,
    DoctorListView,
    DoctorSlotListView,
    HoldView,
    MedicineCatalogAdminView,
    MedicineCatalogCreateView,
    MedicineCatalogSearchView,
    PatientPostVisitSummaryView,
    RescheduleView,
    SummaryReviewView,
)

app_name = "clinical"

urlpatterns = [
    # ── Patient booking ──────────────────────────────────────────────────────
    path("appointments/hold",                        HoldView.as_view(),           name="appointment-hold"),
    path("appointments/me",                          AppointmentListView.as_view(), name="appointment-list"),
    path("appointments/<uuid:appointment_id>/confirm",    ConfirmView.as_view(),        name="appointment-confirm"),
    path("appointments/<uuid:appointment_id>/hold",       CancelHoldView.as_view(),     name="appointment-cancel-hold"),
    path("appointments/<uuid:appointment_id>/cancel",     CancelView.as_view(),         name="appointment-cancel"),
    path("appointments/<uuid:appointment_id>/reschedule", RescheduleView.as_view(),     name="appointment-reschedule"),
    path("appointments/<uuid:appointment_id>/post-visit-summary", PatientPostVisitSummaryView.as_view(), name="post-visit-summary"),
    path("appointments/<uuid:appointment_id>",            AppointmentDetailView.as_view(), name="appointment-detail"),

    # ── Attachments (Phase 4) ────────────────────────────────────────────────
    path("appointments/<uuid:appointment_id>/attachments",
         AttachmentListCreateView.as_view(), name="attachment-list-create"),
    path("appointments/<uuid:appointment_id>/attachments/<uuid:attachment_id>",
         AttachmentDeleteView.as_view(),     name="attachment-delete"),
    path("appointments/attachments/<uuid:attachment_id>/download",
         AttachmentDownloadView.as_view(),   name="attachment-download"),

    # ── Doctor-facing (Phase 3/5) ─────────────────────────────────────────────
    path("doctor/appointments/<uuid:appointment_id>",
         DoctorAppointmentDetailView.as_view(),  name="doctor-appointment-detail"),
    path("doctor/appointments/<uuid:appointment_id>/consultation",
         ConsultationView.as_view(),             name="doctor-consultation"),
    path("doctor/appointments/<uuid:appointment_id>/summary",
         SummaryReviewView.as_view(),            name="doctor-summary-review"),
    path("doctor/appointments/<uuid:appointment_id>/summary/approve",
         SummaryReviewView.as_view(),            name="doctor-summary-approve"),

    # ── Patient discovery ─────────────────────────────────────────────────────
    path("doctors",                          DoctorListView.as_view(),     name="doctor-list"),
    path("doctors/<uuid:doctor_id>/slots",   DoctorSlotListView.as_view(), name="doctor-slot-list"),

    # ── Medicine catalog (Phase 5) ────────────────────────────────────────────
    path("medicine-catalog",                 MedicineCatalogSearchView.as_view(),  name="medicine-catalog-search"),
    path("medicine-catalog/search",          MedicineCatalogSearchView.as_view(),  name="medicine-catalog-search-alias"),
    path("medicine-catalog/new",             MedicineCatalogCreateView.as_view(),  name="medicine-catalog-create"),
    path("medicine-catalog/<uuid:medicine_id>", MedicineCatalogAdminView.as_view(), name="medicine-catalog-admin"),
]
