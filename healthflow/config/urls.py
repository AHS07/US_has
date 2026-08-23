"""HealthFlow root URL configuration."""
from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import include, path


def healthcheck(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


urlpatterns = [
    # Health check — unauthenticated, used by Docker and load balancers
    path("health/", healthcheck),

    # Django admin (standard, for superuser access)
    path("django-admin/", admin.site.urls),

    # Auth: /auth/login, /auth/refresh, /auth/logout, /auth/forgot-password, etc.
    path("auth/", include("apps.accounts.urls", namespace="auth")),

    # Admin portal API: /admin-api/...
    path("admin-api/", include("apps.accounts.admin_urls", namespace="admin_api")),

    # Scheduling: /doctors, /admin-api/doctors/:id/slots, etc.
    path("", include("apps.scheduling.urls", namespace="scheduling")),

    # Clinical: /appointments, /doctor/appointments, /medicine-catalog, etc.
    path("", include("apps.clinical.urls", namespace="clinical")),

    # Notifications: /notifications
    path("", include("apps.notifications.urls", namespace="notifications")),
]

# django-debug-toolbar — only active in dev when the package is installed
if settings.DEBUG:
    try:
        import debug_toolbar  # noqa: F401
        urlpatterns = [path("__debug__/", include("debug_toolbar.urls"))] + urlpatterns
    except ImportError:
        pass
