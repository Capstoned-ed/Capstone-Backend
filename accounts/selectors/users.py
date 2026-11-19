from django.contrib.auth import get_user_model
from ..models import Role

User = get_user_model()


def list_active_staff_directory():
    """
    Returns active staff, registrar, and admin accounts ordered for directory display.
    """
    return User.objects.filter(
        is_active=True,
        role__in=[Role.STAFF, Role.REGISTRAR, Role.ADMIN]
    ).order_by('role', 'last_name', 'first_name')


def list_users_for_admin(requester_user=None):
    """
    Returns all users for admin management.
    Hides superuser records if the requester is not a superuser.
    """
    qs = User.objects.all().order_by('-date_joined')
    if (
        requester_user
        and getattr(requester_user, 'is_authenticated', False)
        and not getattr(requester_user, 'is_superuser', False)
    ):
        qs = qs.filter(is_superuser=False)
    return qs

