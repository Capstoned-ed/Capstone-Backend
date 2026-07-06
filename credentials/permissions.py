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


class CredentialRequestPermission(permissions.BasePermission):
    """
    Permissions for CredentialRequest:
    - POST: Only Students can create requests.
    - SAFE_METHODS: All authenticated users can access
      (filtered by queryset/object perms).
    - Object level: Students can only access their own requests. Others can access all.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method == 'POST':
            return request.user.role == Role.STUDENT

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.user == request.user
        return True
