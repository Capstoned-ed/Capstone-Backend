from accounts.models import Role
from ..models import CredentialType


def list_credential_types(user=None):
    """
    Returns credential types ordered by name.
    Hides inactive types from non-administrative users.
    """
    qs = CredentialType.objects.all().order_by('name')
    if (
        user
        and getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) not in [Role.ADMIN, Role.REGISTRAR]
    ):
        return qs.filter(is_active=True)
    return qs
