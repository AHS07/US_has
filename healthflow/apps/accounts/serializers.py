"""
accounts/serializers.py

All serializers for auth flows, user creation, and password management.
Validation lives here. Views orchestrate. Business logic stays out of both.
"""
from __future__ import annotations

import hashlib
from typing import Any

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

from apps.accounts.models import PasswordResetToken, User

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_token_pair(user: User) -> dict[str, str]:
    """Return a fresh JWT access + refresh token pair with custom claims."""
    refresh = JWTRefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    refresh["user_id"] = str(user.id)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


# ─── Auth serializers ─────────────────────────────────────────────────────────

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"],
            password=attrs["password"],
        )
        if not user:
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("Account is disabled.")
        attrs["user"] = user
        return attrs


class TokenResponseSerializer(serializers.Serializer):
    """Shape of the token response — used for documentation / response shaping only."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    must_reset_password = serializers.BooleanField()
    role = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            token = JWTRefreshToken(attrs["refresh"])
            user = User.objects.get(id=token["user_id"])
        except Exception:
            raise serializers.ValidationError(
                "Invalid or expired refresh token."
            ) from None
        attrs["user"] = user
        attrs["token"] = token
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        # Always return 200 regardless — don't leak whether an account exists
        return value.lower()


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages)) from e
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        token_hash = hashlib.sha256(attrs["token"].encode()).hexdigest()
        try:
            reset_token = PasswordResetToken.objects.select_related("user").get(
                token_hash=token_hash,
                used_at__isnull=True,
            )
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError(
                {"token": "Invalid or expired reset token."}
            ) from None
        if not reset_token.is_valid:
            raise serializers.ValidationError({"token": "This reset link has expired."})
        attrs["reset_token"] = reset_token
        return attrs


# ─── Hospital bootstrap ───────────────────────────────────────────────────────

class HospitalBootstrapSerializer(serializers.Serializer):
    """
    POST /admin/hospitals — creates the first hospital + its first admin.
    Only works when no hospitals exist yet (enforced in the view).
    """
    hospital_name = serializers.CharField(max_length=200)
    hospital_address = serializers.CharField(required=False, default="")
    contact_email = serializers.EmailField()
    admin_name = serializers.CharField(max_length=200)
    admin_email = serializers.EmailField()
    admin_password = serializers.CharField(write_only=True, min_length=8)

    def validate_admin_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages)) from e
        return value

    def validate_admin_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()


# ─── Admin staff-creation serializers ────────────────────────────────────────

class CreateAdminSerializer(serializers.Serializer):
    """POST /admin/admins — add another admin to the same hospital."""
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, default="")

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()


class CreateDoctorSerializer(serializers.Serializer):
    """POST /admin/doctors — create a doctor account. Temp password emailed."""
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, default="")
    specialization = serializers.CharField(max_length=100)

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()


class CreatePatientSerializer(serializers.Serializer):
    """POST /admin/patients — create a patient account. Temp password emailed."""
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, default="")

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()


# ─── User read serializers ────────────────────────────────────────────────────

class UserProfileSerializer(serializers.ModelSerializer):
    hospital_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email", "phone", "role", "hospital_id", "hospital_name",
                  "must_reset_password", "created_at"]
        read_only_fields = fields

    def get_hospital_name(self, obj: User) -> str | None:
        return obj.hospital.name if obj.hospital else None


class PatientProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["name", "phone"]

    def validate_phone(self, value: str) -> str:
        return value.strip()
