"""
common/scoping.py

Tenancy-scoping layer — the single place that knows how to scope a queryset
by the requesting user's role.

Every viewset that touches appointments, prescriptions, visit_notes,
notifications, pre_visit_attachments, or any table with a patient_id /
hospital_id column MUST inherit from ScopedQuerysetMixin or call scope().

Never write a raw Model.objects.filter(...) against these tables in a view.
Extend this mixin if the current scoping logic does not fit a new endpoint
rather than adding a one-off condition inline — that is how isolation bugs
are introduced.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.exceptions import PermissionDenied

if TYPE_CHECKING:
    from django.db.models import QuerySet


class ScopedQuerysetMixin:
    """
    Mix into any DRF APIView or ViewSet that touches patient-owned or
    hospital-owned data. Call self.scope(qs) inside get_queryset() or any
    method that retrieves rows.

    Scoping rules:
      Patient  -> filters by patient_id = current user id
      Doctor   -> filters by hospital_id = current user's hospital
      Admin    -> filters by hospital_id = current user's hospital

    The field names ``patient_id`` and ``hospital_id`` are the Django ORM
    lookup names — make sure the model has those FK columns or adjust the
    subclass by overriding ``scope()``.
    """

    def scope(self, queryset: QuerySet) -> QuerySet:
        user = self.request.user  # type: ignore[attr-defined]

        if user.role == "patient":
            return queryset.filter(patient_id=user.id)

        if user.role in ("doctor", "admin"):
            if not user.hospital_id:
                raise PermissionDenied("User has no associated hospital.")
            return queryset.filter(hospital_id=user.hospital_id)

        raise PermissionDenied("Unknown role — access denied.")

    def scope_or_404(self, queryset: QuerySet, **kwargs) -> object:
        """
        Scope a queryset then retrieve a single object by kwargs.
        Raises NotFound (404) rather than leaking whether the object exists at all.
        This is the correct pattern for detail endpoints — returning 403 when
        the row exists but belongs to another user would confirm its existence.
        """
        from rest_framework.exceptions import NotFound

        try:
            return self.scope(queryset).get(**kwargs)
        except queryset.model.DoesNotExist:
            raise NotFound(
                f"{queryset.model.__name__} not found."
            ) from None
