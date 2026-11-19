from django.db.models import Model
from rest_framework.permissions import BasePermission
from .models import Role


def _check_live_user_role(request, allowed_roles):
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return False

    # Check live DB state for authenticated model instances
    if isinstance(user, Model) and user.pk is not None:
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        row = UserModel.objects.filter(pk=user.pk).values(
            'role', 'is_active'
        ).first()
        if not row or not row['is_active']:
            return False
        user.role = row['role']
        user.is_active = row['is_active']
        return user.role in allowed_roles

    # Fallback for mock/test objects without database backing
    return bool(
        getattr(user, 'is_active', True) and
        getattr(user, 'role', None) in allowed_roles
    )


class IsStudent(BasePermission):
    """Allows access only to active users with the Student role."""
    def has_permission(self, request, view):
        return _check_live_user_role(request, [Role.STUDENT])


class IsStaffRole(BasePermission):
    """Allows access only to active users with the Staff role."""
    def has_permission(self, request, view):
        return _check_live_user_role(request, [Role.STAFF])


class IsRegistrar(BasePermission):
    """Allows access only to active users with the Registrar role."""
    def has_permission(self, request, view):
        return _check_live_user_role(request, [Role.REGISTRAR])


class IsAdminRole(BasePermission):
    """Allows access only to active users with the Admin role."""
    def has_permission(self, request, view):
        return _check_live_user_role(request, [Role.ADMIN])


class IsStaffOrAdmin(BasePermission):
    """Allows access to active staff, registrar, or admin users."""
    def has_permission(self, request, view):
        return _check_live_user_role(
            request, [Role.STAFF, Role.REGISTRAR, Role.ADMIN]
        )
