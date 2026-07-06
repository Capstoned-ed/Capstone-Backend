from rest_framework import permissions
from accounts.models import Role


class IsAdminOrRegistrarOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow Admins or Registrars to edit it.
    Read-only permissions are allowed for any authenticated request.
    """
    def has_permission(self, request, view):
        # Read permissions are allowed to any authenticated request,
        if request.method in permissions.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)

        # Write permissions are only allowed to Admin or Registrar
        return bool(
            request.user and request.user.is_authenticated and
            request.user.role in [Role.ADMIN, Role.REGISTRAR]
        )
