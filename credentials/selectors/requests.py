import uuid
from django.contrib.auth import get_user_model
from django.db import models

from accounts.models import Role
from ..models import CredentialRequest

User = get_user_model()


def list_credential_requests(user, query_params=None):
    """
    Returns filtered CredentialRequest queryset based on user role and query params.
    Supports queue assignment filtering, name/email lookup, and student data isolation.
    """
    if query_params is None:
        query_params = {}

    qs = CredentialRequest.objects.select_related(
        'user', 'credential_type', 'assigned_staff'
    ).prefetch_related(
        'payments',
        'documents'
    ).order_by('-created_at')

    status_param = query_params.get('status')
    if status_param:
        qs = qs.filter(status=status_param)

    assigned_param = (
        query_params.get('assigned_to') or
        query_params.get('assigned_staff')
    )
    assigned_only = query_params.get('assigned_only')

    if assigned_param:
        raw_target = str(assigned_param).strip()
        if (
            raw_target.lower() == 'me'
            and getattr(user, 'is_authenticated', False)
        ):
            target_user = user
        else:
            target_user = User.objects.filter(
                models.Q(username__iexact=raw_target) |
                models.Q(
                    id=int(raw_target) if raw_target.isdigit() else -1
                )
            ).first()
            if not target_user and ' ' in raw_target:
                parts = raw_target.split(None, 1)
                target_user = User.objects.filter(
                    first_name__iexact=parts[0],
                    last_name__iexact=parts[1]
                ).first()
            if not target_user:
                target_user = User.objects.filter(
                    models.Q(first_name__iexact=raw_target) |
                    models.Q(last_name__iexact=raw_target) |
                    models.Q(email__iexact=raw_target)
                ).first()

        if target_user:
            assigned_q = (
                models.Q(assigned_staff=target_user) |
                models.Q(
                    remarks__icontains=f"Assigned to: {target_user.username}"
                )
            )
            target_full_name = (
                f"{getattr(target_user, 'first_name', '')} "
                f"{getattr(target_user, 'last_name', '')}"
            ).strip()
            if target_full_name:
                assigned_q |= models.Q(
                    remarks__icontains=f"Assigned to: {target_full_name}"
                )
            qs = qs.filter(assigned_q)
        else:
            qs = qs.none()
    elif assigned_only == 'true' and getattr(user, 'is_authenticated', False):
        qs = qs.filter(
            models.Q(assigned_staff=user) |
            models.Q(remarks__icontains=f"Assigned to: {user.username}")
        )

    if (
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) == Role.STUDENT
    ):
        return qs.filter(user=user)

    return qs


def get_credential_request_by_id_or_tracking(lookup_value, queryset=None):
    """
    Attempts to retrieve a CredentialRequest by UUID primary key or tracking number.
    Returns None if neither matches.
    """
    if queryset is None:
        queryset = CredentialRequest.objects.all()

    clean_value = str(lookup_value).strip()

    # 1. Attempt lookup by UUID pk
    try:
        uuid_val = uuid.UUID(clean_value)
        obj = queryset.filter(pk=uuid_val).first()
        if obj:
            return obj
    except (ValueError, TypeError, AttributeError):
        pass

    # 2. Attempt lookup by tracking_number
    return queryset.filter(tracking_number__iexact=clean_value).first()
