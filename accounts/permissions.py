from rest_framework.permissions import BasePermission
from .models import Role


class IsStudent(BasePermission):
    """Allows access only to users with the Student role."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == Role.STUDENT
        )


class IsStaffRole(BasePermission):
    """Allows access only to users with the Staff role."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == Role.STAFF
        )


class IsRegistrar(BasePermission):
    """Allows access only to users with the Registrar role."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == Role.REGISTRAR
        )


class IsAdminRole(BasePermission):
    """Allows access only to users with the Admin role."""
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == Role.ADMIN
        )
