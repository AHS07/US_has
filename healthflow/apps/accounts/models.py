"""
accounts/models.py

Models: Hospital, User (custom AUTH_USER_MODEL), PasswordResetToken, RefreshToken

Rules:
- hospital_id is NULL only for patients (enforced in application layer + clean())
- must_reset_password=True on all admin-created accounts until first forced reset
- No secrets stored in plain text — password_hash is handled by Django's AbstractBaseUser
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

# ─── Hospital ────────────────────────────────────────────────────────────────

class Hospital(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    address = models.TextField(blank=True, default="")
    contact_email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hospitals"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# ─── User ─────────────────────────────────────────────────────────────────────

class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    DOCTOR = "doctor", "Doctor"
    PATIENT = "patient", "Patient"


class UserManager(BaseUserManager["User"]):
    def create_user(
        self,
        email: str,
        password: str,
        role: str = UserRole.PATIENT,
        **extra_fields,
    ) -> User:
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user: User = self.model(email=email, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields) -> User:
        extra_fields.setdefault("role", UserRole.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("must_reset_password", False)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Unified user table for admin, doctor, and patient roles.
    Differentiated by the `role` field.
    hospital_id is NULL only for patients — enforced in clean() and the admin-creation flow.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hospital = models.ForeignKey(
        Hospital,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
        db_column="hospital_id",
    )
    role = models.CharField(max_length=10, choices=UserRole.choices)
    name = models.TextField()
    email = models.EmailField(unique=True)
    phone = models.TextField(blank=True, default="")
    must_reset_password = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_users",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Required by Django's permission system
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name", "role"]

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["hospital_id"], name="idx_users_hospital"),
            models.Index(fields=["role"], name="idx_users_role"),
        ]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}> [{self.role}]"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.role in (UserRole.ADMIN, UserRole.DOCTOR) and self.hospital_id is None:
            raise ValidationError(
                {"hospital": f"A user with role '{self.role}' must belong to a hospital."}
            )

    # Django generates hospital_id automatically from the ForeignKey — no override needed.


# ─── PasswordResetToken ───────────────────────────────────────────────────────

class PasswordResetToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    token_hash = models.TextField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "password_reset_tokens"
        indexes = [
            models.Index(fields=["user"], name="idx_reset_tokens_user"),
        ]

    def __str__(self) -> str:
        return f"PasswordResetToken for {self.user_id} (expires {self.expires_at})"

    @property
    def is_valid(self) -> bool:
        from django.utils import timezone
        return self.used_at is None and self.expires_at > timezone.now()


# ─── RefreshToken ─────────────────────────────────────────────────────────────

class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.TextField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refresh_tokens"
        indexes = [
            models.Index(fields=["user"], name="idx_refresh_tokens_user"),
        ]

    def __str__(self) -> str:
        return f"RefreshToken for {self.user_id}"
