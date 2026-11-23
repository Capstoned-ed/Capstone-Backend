from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle
from drf_spectacular.utils import extend_schema
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    CustomTokenObtainPairSerializer,
    UserSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    SelfProfileUpdateSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    PasswordResetConfirmSerializer,
    ChangePasswordSerializer,
)
from .permissions import IsAdminRole, IsStaffOrAdmin
from .models import Role
from .services import AccountService, PasswordResetService

User = get_user_model()


class CurrentUserView(APIView):
    """
    Returns the authenticated user's profile and details.
    Accessible to any authenticated user (Student, Staff, Registrar, Admin).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer})
    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=SelfProfileUpdateSerializer,
        responses={200: UserSerializer}
    )
    def patch(self, request, *args, **kwargs):
        serializer = SelfProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = AccountService.update_user(
            actor=request.user,
            user=request.user,
            validated_data=serializer.validated_data,
        )
        return Response(UserSerializer(updated).data, status=status.HTTP_200_OK)


class StaffDirectoryView(APIView):
    """
    Returns active staff, registrar, and admin accounts for staff assignment,
    workload distribution, and staff directory.
    Accessible to Staff, Registrar, and Admin.
    """
    permission_classes = [IsAuthenticated, IsStaffOrAdmin]

    @extend_schema(responses={200: UserSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        role_param = request.query_params.get('role')
        if role_param:
            qs = User.objects.filter(
                is_active=True,
                role__iexact=role_param
            ).order_by('last_name', 'first_name')
        else:
            qs = User.objects.filter(
                is_active=True,
                role__in=[Role.STAFF, Role.REGISTRAR, Role.ADMIN]
            ).order_by('role', 'last_name', 'first_name')
        serializer = UserSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Takes a set of user credentials and returns an access and refresh JSON web
    token pair to prove the authentication of those credentials.
    Includes custom claims for RBAC.
    """
    serializer_class = CustomTokenObtainPairSerializer


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows admins to view or edit users.
    Supports soft deletion.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get_permissions(self):
        # Allow Staff, Registrar, and Admin to list users (e.g. role=STAFF)
        if self.action == 'list':
            return [IsAuthenticated(), IsStaffOrAdmin()]
        return [IsAuthenticated(), IsAdminRole()]

    def get_queryset(self):
        qs = User.objects.all().order_by('-date_joined')
        if (self.request.user.is_authenticated and
                not self.request.user.is_superuser):
            qs = qs.filter(is_superuser=False)
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role__iexact=role)
        # Non-admin users can only see active staff/registrar/admin users
        if (self.request.user.is_authenticated and
                self.request.user.role not in [Role.ADMIN]):
            qs = qs.filter(
                role__in=[Role.STAFF, Role.REGISTRAR, Role.ADMIN],
                is_active=True
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserSerializer

    @extend_schema(responses={201: UserSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = AccountService.create_user(
            actor=request.user,
            **serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @extend_schema(responses={200: UserSerializer})
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        if str(instance.id) == str(request.user.id):
            req_role = request.data.get('role')
            if req_role and req_role != instance.role:
                return Response(
                    {"detail": "You cannot change your own administrative role."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if 'is_active' in request.data and not request.data['is_active']:
                return Response(
                    {
                        "detail": (
                            "You cannot deactivate your own administrative account."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            req_username = (
                request.data.get('username')
                or request.data.get('student_id')
                or request.data.get('employee_id')
            )
            if (
                req_username and
                str(req_username).strip().lower() !=
                str(instance.username).strip().lower()
            ):
                return Response(
                    {"detail": "You cannot modify your own User ID."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        user = AccountService.update_user(
            actor=request.user,
            user=instance,
            validated_data=serializer.validated_data
        )

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        return Response(UserSerializer(user).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if str(instance.id) == str(request.user.id):
            return Response(
                {"detail": "You cannot deactivate your own administrative account."},
                status=status.HTTP_400_BAD_REQUEST
            )
        AccountService.deactivate_user(
            actor=request.user,
            user=instance
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: UserSerializer})
    @action(
        detail=False,
        methods=['get', 'patch'],
        permission_classes=[IsAuthenticated],
    )
    def me(self, request):
        if request.method == 'GET':
            return Response(UserSerializer(request.user).data)

        serializer = SelfProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = AccountService.update_user(
            actor=request.user,
            user=request.user,
            validated_data=serializer.validated_data,
        )
        return Response(UserSerializer(updated).data)


class PasswordResetRequestView(APIView):
    """
    Public endpoint to request a 6-digit OTP for password reset.
    Returns 200 OK regardless of whether the email exists (anti-enumeration).
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    @extend_schema(
        request=PasswordResetRequestSerializer,
        responses={200: dict}
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = PasswordResetService.request_otp(
            serializer.validated_data['email']
        )
        return Response(result, status=status.HTTP_200_OK)


class PasswordResetVerifyView(APIView):
    """
    Public endpoint to verify an OTP before submitting new password.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    @extend_schema(
        request=PasswordResetVerifySerializer,
        responses={200: dict}
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            PasswordResetService.verify_otp(
                serializer.validated_data['email'],
                serializer.validated_data['otp']
            )
            return Response(
                {"detail": "Verification code is valid."},
                status=status.HTTP_200_OK
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": str(exc.message if hasattr(exc, 'message') else exc)},
                status=status.HTTP_400_BAD_REQUEST
            )


class PasswordResetConfirmView(APIView):
    """
    Public endpoint to verify OTP and reset password.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={200: dict}
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            PasswordResetService.reset_password(
                serializer.validated_data['email'],
                serializer.validated_data['otp'],
                serializer.validated_data['new_password']
            )
            return Response(
                {"detail": "Password has been reset successfully."},
                status=status.HTTP_200_OK
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": str(exc.message if hasattr(exc, 'message') else exc)},
                status=status.HTTP_400_BAD_REQUEST
            )


class ChangePasswordView(APIView):
    """
    Authenticated endpoint to change the current user's password.
    Accessible to all roles (Student, Staff, Registrar, Admin).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={200: dict}
    )
    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            AccountService.change_password(
                user=request.user,
                current_password=serializer.validated_data['current_password'],
                new_password=serializer.validated_data['new_password']
            )
            return Response(
                {"detail": "Password changed successfully."},
                status=status.HTTP_200_OK
            )
        except DjangoValidationError as exc:
            msg = exc.message if hasattr(exc, 'message') else str(exc)
            return Response(
                {"detail": msg},
                status=status.HTTP_400_BAD_REQUEST
            )
