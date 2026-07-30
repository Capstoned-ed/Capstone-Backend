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

        if request.method == 'PATCH':
            return request.user.role in [
                Role.STAFF, Role.REGISTRAR, Role.ADMIN, Role.STUDENT
            ]

        if request.method not in permissions.SAFE_METHODS:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.user == request.user
        return True


class RequirementDocumentPermission(permissions.BasePermission):
    """
    Permissions for RequirementDocument:
    - POST: Only Students can upload documents.
    - SAFE_METHODS: All authenticated users can access
      (filtered by queryset/object perms).
    - Object level: Students can only access documents for their own requests.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method == 'POST':
            return request.user.role == Role.STUDENT

        if request.method not in permissions.SAFE_METHODS:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.request.user == request.user
        return True


class StudentClearancePermission(permissions.BasePermission):
    """
    Permissions for StudentClearance:
    - POST: Only Students can upload clearances.
    - PATCH (review): Only Staff and Admins.
    - SAFE_METHODS: Students can view their own, Staff/Admins can view all.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method == 'POST':
            return request.user.role == Role.STUDENT

        if request.method in ['PUT', 'PATCH']:
            # Assume detail view for review. Only Staff and Admin.
            return request.user.role in [Role.STAFF, Role.ADMIN]

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.user == request.user
        if request.user.role in [Role.STAFF, Role.ADMIN]:
            return True
        return False


class PaymentPermission(permissions.BasePermission):
    """
    Permissions for Payment:
    - POST: Students (for their own requests).
    - PATCH (verify): Staff and Admin only.
    - SAFE_METHODS: All authenticated users (filtered by queryset).
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method == 'POST':
            return request.user.role == Role.STUDENT

        if request.method == 'PATCH' and view.action == 'verify':
            return request.user.role in [Role.STAFF, Role.ADMIN]

        if request.method not in permissions.SAFE_METHODS:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.request.user == request.user
        return True
