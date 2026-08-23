"""
notifications/urls.py — Phase 6 notification + calendar routes.
Mounted at "" in config/urls.py.

Patient notifications:
  GET    /notifications
  PATCH  /notifications/:id/read
  POST   /notifications/read-all

Google Calendar OAuth (doctor):
  GET    /doctor/calendar/connect
  GET    /doctor/calendar/callback
  DELETE /doctor/calendar/disconnect
  GET    /doctor/calendar/status
"""
from django.urls import path

from apps.notifications.views import (
    CalendarCallbackView,
    CalendarConnectView,
    CalendarDisconnectView,
    CalendarStatusView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
)

app_name = "notifications"

urlpatterns = [
    # Patient notifications
    path("notifications",                       NotificationListView.as_view(),       name="notification-list"),
    path("notifications/read-all",              NotificationMarkAllReadView.as_view(), name="notification-read-all"),
    path("notifications/<uuid:notification_id>/read", NotificationMarkReadView.as_view(), name="notification-mark-read"),

    # Google Calendar OAuth
    path("doctor/calendar/connect",    CalendarConnectView.as_view(),    name="calendar-connect"),
    path("doctor/calendar/callback",   CalendarCallbackView.as_view(),   name="calendar-callback"),
    path("doctor/calendar/disconnect", CalendarDisconnectView.as_view(), name="calendar-disconnect"),
    path("doctor/calendar/status",     CalendarStatusView.as_view(),     name="calendar-status"),
]
