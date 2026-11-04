from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from pathlib import Path
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from .models import (
    CredentialType,
    CredentialRequest,
    RequirementDocument,
    StudentClearance,
    Payment
)
from .serializers import (
    CredentialTypeSerializer,
    CredentialTypeCreateUpdateSerializer,
    CredentialRequestSerializer,
    RequirementDocumentSerializer,
    StudentClearanceSerializer,
    StudentClearanceSubmitSerializer,
    StudentClearanceReviewSerializer,
    PaymentSerializer
)
from .permissions import (
    IsAdminOrRegistrarOrReadOnly,
    CredentialRequestPermission,
    RequirementDocumentPermission,
    StudentClearancePermission,
    PaymentPermission
)
from .services import (
    CredentialTypeService,
    CredentialRequestService,
    RequirementDocumentService,
    StudentClearanceService,
    PaymentService
)
from accounts.models import Role
from .ml_client import MLClient


class CredentialTypeViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing credential types.
    """
    # Base queryset for router URL introspection; actual filtering in get_queryset().
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
        ).prefetch_related(
            'payments',
            'documents'
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

        if not document.file or not document.file.storage.exists(document.file.name):
            return Response(
                {"detail": "Document file not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        filename = Path(document.file.name).name
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

        filename = Path(clearance.file.name).name
        return FileResponse(
            clearance.file.open('rb'),
            as_attachment=True,
            filename=filename
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing OTC payments.
    """
    serializer_class = PaymentSerializer
    permission_classes = [PaymentPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = Payment.objects.select_related(
            'request__user'
        ).order_by('-uploaded_at')
        user = self.request.user

        if user.is_authenticated and user.role == Role.STUDENT:
            return qs.filter(request__user=user)

        return qs

    @extend_schema(responses={201: PaymentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        req = serializer.validated_data['request']
        if request.user.role == Role.STUDENT and req.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        payment = PaymentService.submit_payment(
            actor=request.user,
            request=req,
            amount=serializer.validated_data['amount'],
            receipt_image=serializer.validated_data['receipt_image'],
            receipt_reference_number=serializer.validated_data.get(
                'receipt_reference_number', '')
        )
        headers = self.get_success_headers(serializer.data)
        return Response(
            PaymentSerializer(payment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        payment = self.get_object()

        if not payment.receipt_image or not payment.receipt_image.storage.exists(
            payment.receipt_image.name
        ):
            return Response(
                {"detail": "Receipt file not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        filename = Path(payment.receipt_image.name).name
        return FileResponse(
            payment.receipt_image.open('rb'),
            as_attachment=True,
            filename=filename
        )

    @extend_schema(responses={200: PaymentSerializer})
    @action(detail=True, methods=['patch'])
    def verify(self, request, pk=None):
        payment = self.get_object()

        action_type = request.data.get('action')
        remarks = request.data.get('remarks', '')

        if not action_type:
            return Response(
                {"detail": "action is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        updated_payment = PaymentService.verify_payment(
            actor=request.user,
            payment=payment,
            action=action_type,
            remarks=remarks
        )

        return Response(PaymentSerializer(updated_payment).data)

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class PredictTurnaroundView(APIView):
    """
    Predict estimated credential processing duration.
    Accessible to all authenticated users (Students, Staff, Registrars, Admins).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cred_code = request.query_params.get('credential_type') or request.query_params.get('code', 'TOR')
        purpose = request.query_params.get('purpose', 'Employment')
        date_requested = request.query_params.get('date_requested')
        num_docs = int(request.query_params.get('num_documents', 1))

        res = MLClient.predict_processing_time(
            credential_code=cred_code,
            purpose=purpose,
            date_requested=date_requested,
            num_documents=num_docs
        )
        return Response(res, status=status.HTTP_200_OK)

    def post(self, request):
        cred_code = request.data.get('credential_type', 'TOR')
        purpose = request.data.get('purpose', 'Employment')
        date_requested = request.data.get('date_requested')
        num_docs = int(request.data.get('num_documents', 1))

        res = MLClient.predict_processing_time(
            credential_code=cred_code,
            purpose=purpose,
            date_requested=date_requested,
            num_documents=num_docs
        )
        return Response(res, status=status.HTTP_200_OK)


class AdminDailyForecastView(APIView):
    """
    Daily incoming credential request forecasting.
    Restricted to Staff, Registrars, and Administrators.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {"detail": "Only staff and administrators can access daily demand forecasting."},
                status=status.HTTP_403_FORBIDDEN
            )

        start_date = request.query_params.get('start_date')
        if not start_date:
            from datetime import datetime, timedelta
            start_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            
        op_days = int(request.query_params.get('operating_days', 20))
        res = MLClient.forecast_daily_demand(start_date=start_date, operating_days=op_days)
        return Response(res, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {"detail": "Only staff and administrators can access daily demand forecasting."},
                status=status.HTTP_403_FORBIDDEN
            )

        start_date = request.data.get('start_date')
        if not start_date:
            from datetime import datetime, timedelta
            start_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            
        op_days = int(request.data.get('operating_days', 20))
        res = MLClient.forecast_daily_demand(start_date=start_date, operating_days=op_days)
        return Response(res, status=status.HTTP_200_OK)


class AdminMonthlyWorkloadView(APIView):
    """
    Monthly workload volume forecasting and classification.
    Restricted to Staff, Registrars, and Administrators.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {"detail": "Only staff and administrators can access monthly workload forecasting."},
                status=status.HTTP_403_FORBIDDEN
            )

        target_month = request.query_params.get('target_month')
        res = MLClient.forecast_monthly_workload(target_month=target_month)
        return Response(res, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.role not in [Role.STAFF, Role.REGISTRAR, Role.ADMIN]:
            return Response(
                {"detail": "Only staff and administrators can access monthly workload forecasting."},
                status=status.HTTP_403_FORBIDDEN
            )

        target_month = request.data.get('target_month')
        res = MLClient.forecast_monthly_workload(target_month=target_month)
        return Response(res, status=status.HTTP_200_OK)


class MLHealthStatusView(APIView):
    """
    Health and status check for ML microservice integration.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MLClient.get_health(), status=status.HTTP_200_OK)
