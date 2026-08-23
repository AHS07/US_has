"""
notifications/views.py

Phase 6 endpoints:

Patient notifications:
  GET    /notifications             — list (most recent 50, unread first)
  PATCH  /notifications/:id/read    — mark one notification as read
  POST   /notifications/read-all    — mark all as read

Google Calendar OAuth (doctor):
  GET    /doctor/calendar/connect        — redirect to Google OAuth consent screen
  GET    /doctor/calendar/callback       — OAuth callback, saves credentials
  DELETE /doctor/calendar/disconnect     — revoke and delete credentials
  GET    /doctor/calendar/status         — connected true/false + calendar_id
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsDoctor, IsNotForcedReset, IsPatient
from apps.notifications.models import DoctorGoogleCredentials, Notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Patient notifications
# ---------------------------------------------------------------------------

class NotificationListView(APIView):
    """
    GET /notifications?unread_only=true

    Returns the requesting patient's most recent 50 notifications, newest first.
    Scoped by patient_id — no cross-patient access.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        unread_only = request.query_params.get("unread_only", "").lower() == "true"
        qs = (
            Notification.objects
            .filter(patient=request.user)
            .select_related("appointment")
            .order_by("-created_at")[:50]
        )
        if unread_only:
            qs = Notification.objects.filter(
                patient=request.user, is_read=False
            ).select_related("appointment").order_by("-created_at")[:50]

        data = [_serialize_notification(n) for n in qs]
        unread_count = Notification.objects.filter(
            patient=request.user, is_read=False
        ).count()
        return Response({"unread_count": unread_count, "notifications": data})


class NotificationMarkReadView(APIView):
    """
    PATCH /notifications/:id/read  — mark one notification as read.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def patch(self, request: Request, notification_id: str) -> Response:
        try:
            notif = Notification.objects.get(
                id=notification_id, patient=request.user
            )
        except Notification.DoesNotExist:
            raise NotFound("Notification not found.") from None

        notif.is_read = True
        notif.save(update_fields=["is_read"])
        return Response({"id": str(notif.id), "is_read": True})


class NotificationMarkAllReadView(APIView):
    """
    POST /notifications/read-all  — mark all as read.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def post(self, request: Request) -> Response:
        updated = Notification.objects.filter(
            patient=request.user, is_read=False
        ).update(is_read=True)
        return Response({"marked_read": updated})


# ---------------------------------------------------------------------------
# Google Calendar OAuth (doctor)
# ---------------------------------------------------------------------------

class CalendarConnectView(APIView):
    """
    GET /doctor/calendar/connect

    Redirects the doctor to Google's OAuth consent screen.
    Stores the state token in the session for CSRF protection.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        from apps.integrations.calendar.client import GoogleCalendarClient

        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            return Response(
                {"error": {"code": "not_configured",
                           "message": "Google Calendar is not configured on this server."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        flow          = GoogleCalendarClient.build_oauth_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        # Store state in session for callback CSRF validation
        request.session["google_oauth_state"] = state
        return Response({"auth_url": auth_url})


class CalendarCallbackView(APIView):
    """
    GET /doctor/calendar/callback?code=&state=

    Exchanges the authorization code for tokens and saves them (encrypted).
    Called by Google after the doctor approves the consent screen.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        from apps.integrations.calendar.client import GoogleCalendarClient

        code  = request.query_params.get("code",  "")
        state = request.query_params.get("state", "")

        stored_state = request.session.get("google_oauth_state", "")
        if state != stored_state:
            raise ValidationError({"state": "Invalid OAuth state. Please try connecting again."})

        if not code:
            raise ValidationError({"code": "Authorization code missing."})

        flow = GoogleCalendarClient.build_oauth_flow()
        try:
            flow.fetch_token(code=code)
            google_creds = flow.credentials
        except Exception as exc:
            logger.error("CalendarCallbackView: token exchange failed: %s", exc)
            raise ValidationError({"code": "Failed to exchange authorization code."}) from exc

        GoogleCalendarClient.save_credentials(request.user, google_creds)

        try:
            del request.session["google_oauth_state"]
        except KeyError:
            pass

        logger.info("CalendarCallbackView: doctor %s connected Google Calendar", request.user.id)

        # Update DoctorProfile.google_oauth_connected flag
        try:
            request.user.doctor_profile.google_oauth_connected = True
            request.user.doctor_profile.save(update_fields=["google_oauth_connected"])
        except Exception:
            pass

        return Response({"connected": True})


class CalendarDisconnectView(APIView):
    """
    DELETE /doctor/calendar/disconnect

    Revokes the OAuth token and deletes the DoctorGoogleCredentials row.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def delete(self, request: Request) -> Response:
        try:
            creds = DoctorGoogleCredentials.objects.get(doctor=request.user)
        except DoctorGoogleCredentials.DoesNotExist:
            return Response({"connected": False})

        # Best-effort revoke — don't block disconnect if revoke fails
        try:
            from common.encryption import decrypt_token
            import requests as http_requests
            token = decrypt_token(creds.access_token_enc)
            http_requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("CalendarDisconnectView: revoke failed (proceeding): %s", exc)

        creds.delete()

        # Update DoctorProfile flag
        try:
            request.user.doctor_profile.google_oauth_connected = False
            request.user.doctor_profile.save(update_fields=["google_oauth_connected"])
        except Exception:
            pass

        logger.info("CalendarDisconnectView: doctor %s disconnected Google Calendar", request.user.id)
        return Response({"connected": False})


class CalendarStatusView(APIView):
    """
    GET /doctor/calendar/status

    Returns { connected: bool, calendar_id: str | null }
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        try:
            creds = DoctorGoogleCredentials.objects.get(doctor=request.user)
            return Response({
                "connected":   True,
                "calendar_id": creds.calendar_id or "primary",
                "connected_at": creds.connected_at.isoformat(),
            })
        except DoctorGoogleCredentials.DoesNotExist:
            return Response({"connected": False, "calendar_id": None})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _serialize_notification(n: Notification) -> dict:
    return {
        "id":             str(n.id),
        "event_type":     n.event_type,
        "title":          n.title,
        "body":           n.body,
        "is_read":        n.is_read,
        "appointment_id": str(n.appointment_id) if n.appointment_id else None,
        "created_at":     n.created_at.isoformat(),
    }
