from rest_framework import viewsets, status
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
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    PasswordResetConfirmSerializer,
)
from .permissions import IsAdminRole
from .services import AccountService, PasswordResetService

User = get_user_model()


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

    def get_queryset(self):
        qs = User.objects.all().order_by('-date_joined')
        if self.request.user.is_authenticated and not self.request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
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
        AccountService.deactivate_user(
            actor=request.user,
            user=instance
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


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
