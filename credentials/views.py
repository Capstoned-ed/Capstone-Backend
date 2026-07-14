from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance
)
from .serializers import (
    CredentialTypeSerializer,
    CredentialTypeCreateUpdateSerializer,
    CredentialRequestSerializer,
    RequirementDocumentSerializer,
    StudentClearanceSerializer,
    StudentClearanceSubmitSerializer,
    StudentClearanceReviewSerializer
)
from .permissions import (
    IsAdminOrRegistrarOrReadOnly,
    CredentialRequestPermission,
    RequirementDocumentPermission,
    StudentClearancePermission
)
from .services import (
    CredentialTypeService,
    CredentialRequestService,
    RequirementDocumentService,
    StudentClearanceService
)
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

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

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

    @extend_schema(responses={200: CredentialRequestSerializer})
    @action(detail=True, methods=['patch'])
    def transition(self, request, pk=None):
        credential_request = self.get_object()

        new_status = request.data.get('status')
        remarks = request.data.get('remarks', '')

        if not new_status:
            return Response(
                {"detail": "status is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        updated_request = CredentialRequestService.transition_request(
            actor=request.user,
            credential_request=credential_request,
            new_status=new_status,
            remarks=remarks
        )

        return Response(CredentialRequestSerializer(updated_request).data)


class RequirementDocumentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing requirement documents.
    """
    serializer_class = RequirementDocumentSerializer
    permission_classes = [RequirementDocumentPermission]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        qs = RequirementDocument.objects.select_related(
            'request__user'
        ).order_by('-uploaded_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(request__user=user)

        return qs

    @extend_schema(responses={201: RequirementDocumentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = RequirementDocumentService.upload_document(
            actor=request.user,
            validated_data=serializer.validated_data
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            RequirementDocumentSerializer(document).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        document = self.get_object()
        filename = document.file.name.split('/')[-1]
        return FileResponse(
            document.file.open('rb'),
            as_attachment=True,
            filename=filename
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class StudentClearanceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing student clearances.
    """
    permission_classes = [StudentClearancePermission]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        qs = StudentClearance.objects.select_related('user').order_by('-updated_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(user=user)

        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return StudentClearanceSubmitSerializer
        if self.action == 'review':
            return StudentClearanceReviewSerializer
        return StudentClearanceSerializer

    @extend_schema(responses={201: StudentClearanceSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        clearance = StudentClearanceService.submit_clearance(
            actor=request.user,
            file=serializer.validated_data['file']
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            StudentClearanceSerializer(clearance).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @extend_schema(responses={200: StudentClearanceSerializer})
    @action(detail=True, methods=['patch'])
    def review(self, request, pk=None):
        clearance = self.get_object()
        serializer = self.get_serializer(clearance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        updated_clearance = StudentClearanceService.review_clearance(
            actor=request.user,
            clearance=clearance,
            status=serializer.validated_data.get('status'),
            remarks=serializer.validated_data.get('remarks', '')
        )
        return Response(StudentClearanceSerializer(updated_clearance).data)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        clearance = self.get_object()

        # Strict Ownership Check for Download
        if request.user.role == Role.STUDENT and clearance.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        if not clearance.file or not clearance.file.storage.exists(clearance.file.name):
            return Response(
                {"detail": "File not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        filename = clearance.file.name.split('/')[-1]
        return FileResponse(
            clearance.file.open('rb'),
            as_attachment=True,
            filename=filename
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        if self.action != 'review':
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
