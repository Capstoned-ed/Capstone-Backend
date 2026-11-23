from django.db.models import Model
from rest_framework import permissions
from accounts.models import Role


def _sync_live_user(request):
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return False
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
        return True
    return bool(getattr(user, 'is_active', True))


class IsAdminOrRegistrarOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow Admins or Registrars to edit it.
    Read-only permissions are allowed for any authenticated request.
    """

    def has_permission(self, request, view):
        if not _sync_live_user(request):
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        return request.user.role in [Role.ADMIN, Role.REGISTRAR]


class CredentialRequestPermission(permissions.BasePermission):
    """
    Permissions for CredentialRequest:
    - POST: Only Students can create requests.
    - SAFE_METHODS: All authenticated users can access
      (filtered by queryset/object perms).
    - Object level: Students can only access their own requests. Others can access all.
    """

    def has_permission(self, request, view):
        if not _sync_live_user(request):
            return False

        if getattr(view, 'action', None) == 'assign':
            return request.user.role in [
                Role.STAFF, Role.REGISTRAR, Role.ADMIN
            ]

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
        if not _sync_live_user(request):
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
    - PATCH (review): Only Registrar Frontdesk and Admins.
    - SAFE_METHODS: Students view their own, Staff/Registrar/Admins view all.
    """

    def has_permission(self, request, view):
        if not _sync_live_user(request):
            return False

        if request.method == 'POST':
            return request.user.role == Role.STUDENT

        if request.method in ['PUT', 'PATCH']:
            # Clearance review is strictly restricted to Registrar Frontdesk and Admin
            return request.user.role in [Role.REGISTRAR, Role.ADMIN]

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.user == request.user
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]
        return request.user.role in [Role.REGISTRAR, Role.ADMIN]


class PaymentPermission(permissions.BasePermission):
    """
    Permissions for Payment:
    - POST: Students (for their own requests).
    - PATCH (verify): Registrar Frontdesk and Admin only.
    - SAFE_METHODS: All authenticated users (filtered by queryset).
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method == 'POST':
            return request.user.role == Role.STUDENT

        if request.method == 'PATCH' and view.action == 'verify':
            return request.user.role in [Role.REGISTRAR, Role.ADMIN]

        if request.method not in permissions.SAFE_METHODS:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if request.user.role == Role.STUDENT:
            return obj.request.user == request.user
        if request.method in permissions.SAFE_METHODS:
            return request.user.role in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]
        return request.user.role in [Role.REGISTRAR, Role.ADMIN]
