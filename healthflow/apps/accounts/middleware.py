"""
accounts/middleware.py

MustResetPasswordMiddleware — blocks every authenticated request when
must_reset_password=True, except:
  - POST /auth/reset-password  (the reset action itself)
  - POST /auth/logout          (always allow logout)
  - GET/POST /auth/refresh     (allow token refresh so the client can stay alive)
  - Any unauthenticated request (login, forgot-password, etc.)

Returns 403 with a clear message so the frontend can redirect to the
password-reset screen.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.utils.deprecation import MiddlewareMixin

# Paths that bypass the forced-reset check
_EXEMPT_PREFIXES = (
    "/auth/reset-password",
    "/auth/logout",
    "/auth/refresh",
    "/auth/login",
    "/auth/forgot-password",
    "/health/",
    "/django-admin/",
)


class MustResetPasswordMiddleware(MiddlewareMixin):
    def process_request(self, request: HttpRequest):
        # Skip check for exempt paths
        for prefix in _EXEMPT_PREFIXES:
            if request.path.startswith(prefix):
                return None

        # Only check authenticated users
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None

        if getattr(user, "must_reset_password", False):
            return JsonResponse(
                {
                    "error": {
                        "code": "must_reset_password",
                        "message": "You must reset your password before continuing.",
                    }
                },
                status=403,
            )

        return None
