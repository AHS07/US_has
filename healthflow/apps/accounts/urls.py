"""Auth routes — /auth/..."""
from django.urls import path

from apps.accounts.views import (
    ForgotPasswordView,
    LoginView,
    LogoutView,
    PatientMeView,
    RefreshView,
    ResetPasswordView,
)

app_name = "auth"

urlpatterns = [
    path("login", LoginView.as_view(), name="login"),
    path("refresh", RefreshView.as_view(), name="refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("forgot-password", ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password", ResetPasswordView.as_view(), name="reset-password"),
    # Patient self-service profile
    path("patients/me", PatientMeView.as_view(), name="patient-me"),
]
