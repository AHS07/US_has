"""
integrations/calendar/client.py

Google Calendar API client — create, update, delete events.
Also handles OAuth2 token refresh transparently.

Rules:
  - Raw access/refresh tokens are NEVER logged or returned to the caller.
  - Token refresh writes the updated encrypted tokens back to the DB
    in the same call — callers do not need to handle refresh logic.
  - All methods are synchronous (called from Celery tasks, not views).
  - If credentials are expired and refresh fails, GoogleCalendarError is raised
    so the Celery task can retry or mark the job as failed.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class GoogleCalendarError(Exception):
    """Raised on unrecoverable Google Calendar API errors."""


class GoogleCalendarClient:
    """
    Thin wrapper around the Google Calendar API v3.

    Usage:
        creds  = DoctorGoogleCredentials.objects.get(doctor=doctor)
        client = GoogleCalendarClient(creds)
        event_id = client.create_event(appointment)
    """

    def __init__(self, credentials) -> None:
        """
        credentials: apps.notifications.models.DoctorGoogleCredentials instance
        """
        self._creds = credentials
        self._service = None   # lazy — built on first use

    # ── Public API ────────────────────────────────────────────────────────────

    def create_event(self, appointment) -> str:
        """
        Create a new Calendar event for the appointment.
        Returns the Google event_id (stored externally if needed).
        """
        service = self._get_service()
        body    = self._build_event_body(appointment)
        try:
            result = (
                service
                .events()
                .insert(calendarId=self._creds.calendar_id or "primary", body=body)
                .execute()
            )
            event_id = result.get("id", "")
            logger.info(
                "GoogleCalendarClient.create_event: created %s for appt %s",
                event_id, appointment.id,
            )
            return event_id
        except Exception as exc:
            raise GoogleCalendarError(f"create_event failed: {exc}") from exc

    def update_event(self, appointment) -> None:
        """
        Update the existing Calendar event for the appointment.
        Uses persisted google_calendar_event_id when available, falling back to text search.
        """
        service  = self._get_service()
        event_id = getattr(appointment, "google_calendar_event_id", "") or self._find_event_id(service, appointment)
        if not event_id:
            # Not found — create instead (idempotent)
            self.create_event(appointment)
            return
        body = self._build_event_body(appointment)
        try:
            service.events().update(
                calendarId=self._creds.calendar_id or "primary",
                eventId=event_id,
                body=body,
            ).execute()
        except Exception as exc:
            raise GoogleCalendarError(f"update_event failed: {exc}") from exc

    def delete_event(self, appointment) -> None:
        """
        Delete the Calendar event for this appointment.
        Uses persisted google_calendar_event_id when available, falling back to text search.
        """
        service  = self._get_service()
        event_id = getattr(appointment, "google_calendar_event_id", "") or self._find_event_id(service, appointment)
        if not event_id:
            logger.info(
                "GoogleCalendarClient.delete_event: no event found for appt %s — skipping",
                appointment.id,
            )
            return
        try:
            service.events().delete(
                calendarId=self._creds.calendar_id or "primary",
                eventId=event_id,
            ).execute()
        except Exception as exc:
            raise GoogleCalendarError(f"delete_event failed: {exc}") from exc

    # ── OAuth helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def build_oauth_flow():
        """
        Return a google_auth_oauthlib Flow for the doctor OAuth dance.
        Called from the /doctor/calendar/connect view.
        """
        from google_auth_oauthlib.flow import Flow

        return Flow.from_client_config(
            client_config={
                "web": {
                    "client_id":     settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                    "token_uri":     "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar.events"],
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        )

    @staticmethod
    def save_credentials(doctor, google_credentials) -> None:
        """
        Persist fresh Google OAuth credentials to DoctorGoogleCredentials.
        Encrypts tokens at rest via common.encryption.encrypt_token.
        """
        from apps.notifications.models import DoctorGoogleCredentials
        from common.encryption import encrypt_token

        expiry = None
        if google_credentials.expiry:
            expiry = timezone.make_aware(
                google_credentials.expiry,
                timezone.utc,
            ) if google_credentials.expiry.tzinfo is None else google_credentials.expiry

        DoctorGoogleCredentials.objects.update_or_create(
            doctor=doctor,
            defaults={
                "access_token_enc":  encrypt_token(google_credentials.token or ""),
                "refresh_token_enc": encrypt_token(google_credentials.refresh_token or ""),
                "token_expiry":      expiry,
                "scopes":            " ".join(google_credentials.scopes or []),
            },
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_service(self):
        """Build (or return cached) google.calendar.Resource, refreshing tokens if needed."""
        if self._service is not None:
            return self._service

        from common.encryption import decrypt_token
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = self._creds

        try:
            google_creds = Credentials(
                token         = decrypt_token(creds.access_token_enc),
                refresh_token = decrypt_token(creds.refresh_token_enc) if creds.refresh_token_enc else None,
                token_uri     = "https://oauth2.googleapis.com/token",
                client_id     = settings.GOOGLE_OAUTH_CLIENT_ID,
                client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET,
                scopes        = creds.scopes.split() if creds.scopes else [],
                expiry        = creds.token_expiry.replace(tzinfo=None) if creds.token_expiry else None,
            )
        except Exception as exc:
            raise GoogleCalendarError(f"Failed to decrypt credentials: {exc}") from exc

        # Refresh if expired
        if google_creds.expired and google_creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                google_creds.refresh(Request())
                # Persist refreshed tokens
                GoogleCalendarClient.save_credentials(creds.doctor, google_creds)
            except Exception as exc:
                raise GoogleCalendarError(f"Token refresh failed: {exc}") from exc

        try:
            self._service = build("calendar", "v3", credentials=google_creds, cache_discovery=False)
        except Exception as exc:
            raise GoogleCalendarError(f"Failed to build Calendar service: {exc}") from exc

        return self._service

    def _build_event_body(self, appointment) -> dict[str, Any]:
        slot = appointment.slot
        date = slot.date

        def _rfc3339(d: datetime.date, t: datetime.time) -> str:
            dt = datetime.datetime.combine(d, t)
            # Calendar API expects timezone-aware ISO 8601
            return dt.isoformat() + "+00:00"

        return {
            "summary":     f"Appointment with {appointment.doctor.name}",
            "description": (
                f"Patient: {appointment.patient.name}\n"
                f"Token: #{appointment.token or 'TBC'}\n"
                f"HealthFlow appointment ID: {appointment.id}"
            ),
            "start": {
                "dateTime": _rfc3339(date, slot.slot_start),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": _rfc3339(date, slot.slot_end),
                "timeZone": "UTC",
            },
            "attendees": [
                {"email": appointment.doctor.email},
                {"email": appointment.patient.email},
            ],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 60},
                    {"method": "popup",  "minutes": 15},
                ],
            },
        }

    def _find_event_id(self, service, appointment) -> str | None:
        """
        Search the doctor's calendar for an event containing the appointment UUID
        in the description. Returns the Google event_id or None.
        """
        try:
            result = service.events().list(
                calendarId   = self._creds.calendar_id or "primary",
                q            = str(appointment.id),
                maxResults   = 1,
                singleEvents = True,
            ).execute()
            items = result.get("items", [])
            return items[0]["id"] if items else None
        except Exception:
            return None
