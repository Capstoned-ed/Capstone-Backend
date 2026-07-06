from rest_framework import viewsets, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from .models import CredentialType, CredentialRequest
from .serializers import (
    CredentialTypeSerializer,
    CredentialTypeCreateUpdateSerializer,
    CredentialRequestSerializer
)
from .permissions import IsAdminOrRegistrarOrReadOnly, CredentialRequestPermission
from .services import CredentialTypeService, CredentialRequestService
from accounts.models import Role


class CredentialTypeViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing credential types.
    """
    queryset = CredentialType.objects.all().order_by('name')
    permission_classes = [IsAdminOrRegistrarOrReadOnly]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CredentialTypeCreateUpdateSerializer
        return CredentialTypeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if user.is_authenticated and user.role not in [Role.ADMIN, Role.REGISTRAR]:
            return qs.filter(is_active=True)

        return qs

    @extend_schema(responses={201: CredentialTypeSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_type = CredentialTypeService.create_type(
            actor=request.user,
            validated_data=serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            CredentialTypeSerializer(credential_type).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @extend_schema(responses={200: CredentialTypeSerializer})
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        credential_type = CredentialTypeService.update_type(
            actor=request.user,
            credential_type=instance,
            validated_data=serializer.validated_data
        )

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        return Response(CredentialTypeSerializer(credential_type).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        CredentialTypeService.deactivate_type(
            actor=request.user,
            credential_type=instance
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class CredentialRequestViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing credential requests.
    """
    serializer_class = CredentialRequestSerializer
    permission_classes = [CredentialRequestPermission]

    def get_queryset(self):
        qs = CredentialRequest.objects.select_related(
            'user', 'credential_type'
        ).order_by('-created_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(user=user)

        return qs

    @extend_schema(responses={201: CredentialRequestSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_request = CredentialRequestService.create_request(
            actor=request.user,
            validated_data=serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            CredentialRequestSerializer(credential_request).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
