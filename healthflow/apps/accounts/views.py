"""
accounts/views.py

Auth endpoints: login, refresh, logout, forgot-password, reset-password,
and patient profile read/update.

Rules followed:
- Views orchestrate; serializers validate; no business logic inline
- Errors go through common.exceptions.healthflow_exception_handler
- No raw exception text or stack traces in responses
- Email sends enqueued as tasks (Phase 6); in Phase 1 we call a thin
  send helper directly so the flow works end-to-end without Celery
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

from apps.accounts.models import PasswordResetToken, User
from apps.accounts.permissions import IsNotForcedReset, IsPatient
from apps.accounts.serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    PatientProfileUpdateSerializer,
    ResetPasswordSerializer,
    UserProfileSerializer,
    _make_token_pair,
)

# ─── Login ────────────────────────────────────────────────────────────────────

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user: User = serializer.validated_data["user"]
        tokens = _make_token_pair(user)
        return Response(
            {
                **tokens,
                "must_reset_password": user.must_reset_password,
                "role": user.role,
            },
            status=status.HTTP_200_OK,
        )


# ─── Refresh ──────────────────────────────────────────────────────────────────

class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        refresh_str = request.data.get("refresh", "")
        if not refresh_str:
            return Response(
                {"error": {"code": "validation_error", "message": "refresh token required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            old_token = JWTRefreshToken(refresh_str)
            user = User.objects.get(id=old_token["user_id"])
        except (TokenError, User.DoesNotExist, KeyError):
            return Response(
                {"error": {
                    "code": "token_invalid",
                    "message": "Invalid or expired refresh token.",
                }},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        # Rotate: blacklist old, issue new pair
        old_token.blacklist()
        tokens = _make_token_pair(user)
        return Response(tokens, status=status.HTTP_200_OK)


# ─── Logout ───────────────────────────────────────────────────────────────────

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh_str = request.data.get("refresh", "")
        if refresh_str:
            try:
                JWTRefreshToken(refresh_str).blacklist()
            except TokenError:
                pass  # already invalid — still 200, user is logging out
        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


# ─── Forgot password ──────────────────────────────────────────────────────────

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Always 200 — don't leak whether the account exists
            return Response(
                {"detail": "If that email is registered, a reset link has been sent."},
                status=status.HTTP_200_OK,
            )

        # Invalidate any existing tokens for this user
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )

        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        PasswordResetToken.objects.create(
            user=user,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(hours=2),
        )

        _send_reset_email(user, raw_token)

        return Response(
            {"detail": "If that email is registered, a reset link has been sent."},
            status=status.HTTP_200_OK,
        )


# ─── Reset password ───────────────────────────────────────────────────────────

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reset_token: PasswordResetToken = serializer.validated_data["reset_token"]
        user = reset_token.user

        user.set_password(serializer.validated_data["new_password"])
        user.must_reset_password = False
        user.save(update_fields=["password", "must_reset_password"])

        reset_token.used_at = timezone.now()
        reset_token.save(update_fields=["used_at"])

        return Response({"detail": "Password reset successful."}, status=status.HTTP_200_OK)


# ─── Patient profile ─────────────────────────────────────────────────────────

class PatientMeView(APIView):
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request: Request) -> Response:
        serializer = PatientProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserProfileSerializer(request.user).data)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _send_reset_email(user: User, raw_token: str) -> None:
    """
    Send a password reset email. In Phase 1 this calls Django's send_mail
    directly (console backend in dev). Phase 6 will replace this with a
    Celery task that retries on failure.
    """
    reset_url = f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/reset-password?token={raw_token}"
    send_mail(
        subject="Reset your HealthFlow password",
        message=(
            f"Hello {user.name},\n\n"
            f"Click the link below to reset your password. "
            f"This link expires in 2 hours.\n\n"
            f"{reset_url}\n\n"
            f"If you did not request this, ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,  # Phase 6 adds proper retry; don't block the response here
    )


def _send_temp_password_email(user: User, temp_password: str) -> None:
    """
    Send a temp password to a newly created admin/doctor/patient account.
    Phase 6 replaces this with a Celery task.
    """
    send_mail(
        subject="Your HealthFlow account has been created",
        message=(
            f"Hello {user.name},\n\n"
            f"An account has been created for you on HealthFlow.\n\n"
            f"Email: {user.email}\n"
            f"Temporary password: {temp_password}\n\n"
            f"You will be required to set a new password on first login.\n\n"
            f"Do not share this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
