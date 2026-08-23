"""
accounts/permissions.py

Custom DRF permission classes. Every view that restricts by role uses one of
these — never inline role-string comparisons in views.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class IsAdmin(BasePermission):
    """Allow only users with role='admin'."""

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )


class IsDoctor(BasePermission):
    """Allow only users with role='doctor'."""

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "doctor"
        )


class IsPatient(BasePermission):
    """Allow only users with role='patient'."""

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "patient"
        )


class IsAdminOrDoctor(BasePermission):
    """Allow admin or doctor — used for shared read endpoints."""

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("admin", "doctor")
        )


class IsNotForcedReset(BasePermission):
    """
    Deny access when must_reset_password=True.
    Applied globally via MustResetPasswordMiddleware, but also available as
    a per-view guard for belt-and-suspenders on sensitive endpoints.
    Raises a PermissionDenied with a specific code so the client can redirect
    to the password-reset screen.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return True  # unauthenticated requests handled elsewhere
        if request.user.must_reset_password:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                detail="You must reset your password before continuing.",
                code="must_reset_password",
            )
        return True
